import functools
import logging
import sys
import traceback
from pathlib import Path

import click

from multi.errors import GitError
from multi.git_helpers import check_all_on_same_branch
from multi.logging import configure_logging
from multi.paths import Paths

# `branch` is excluded because it reports branch state itself (including
# mismatches); re-running the post-command check would duplicate the output.
# `hooks` subcommands are branch-independent and run in partial install-set
# workspaces, where the check would complain about repos that are not cloned.
COMMANDS_WITHOUT_WORKSPACE_BRANCH_CHECK = {"branch", "doctor", "hooks", "recent-users"}


def get_install_set_from_context() -> str | None:
    ctx = click.get_current_context(silent=True)
    while ctx is not None:
        if ctx.obj and "install_set" in ctx.obj:
            return ctx.obj["install_set"]
        ctx = ctx.parent
    return None


def common_command_wrapper(command_to_wrap: click.Command) -> click.Command:
    """
    Wraps an existing Click command to add common functionality:
    - A --verbose option for detailed logging.
    - Standardized error handling and logging.
    This function modifies the command_to_wrap in-place.
    """
    original_callback = command_to_wrap.callback
    if not original_callback:
        # This should generally not happen if command_to_wrap is created via @click.command
        raise ValueError(
            f"Command '{command_to_wrap.name or 'Unnamed'}' has no callback to wrap."
        )

    @functools.wraps(original_callback)
    def new_wrapped_callback(**kwargs):
        # Pop the verbose flag. It's added by this wrapper to the command's params.
        # Click will pass it in kwargs to this new_callback.
        verbose_value = kwargs.pop("verbose", False)

        # Configure logging based on verbosity
        log_level = logging.DEBUG if verbose_value else logging.INFO
        configure_logging(level=log_level)

        result = None
        try:
            # Call the original command's callback with its intended kwargs
            result = original_callback(**kwargs)
        except Exception as e:
            logger = logging.getLogger(__name__)  # Get logger after configuration
            logger.error(str(e))  # This will use the emoji formatter
            if verbose_value:
                # For verbose mode, also print traceback directly to stderr
                click.secho("\nDebug traceback:", fg="yellow", err=True)
                click.secho(traceback.format_exc(), fg="yellow", err=True)
            sys.exit(1)

        ctx = click.get_current_context(silent=True)
        if isinstance(command_to_wrap, click.Group) and ctx is not None:
            if ctx.invoked_subcommand is not None:
                return result

        # After commands, check that all sub-repos are on their expected branch.
        # Some commands (like doctor) intentionally run even when no workspace is initialized.
        command_names = {command_to_wrap.name}
        if ctx is not None:
            command_names.update(ctx.command_path.split()[1:])
        if command_names & COMMANDS_WITHOUT_WORKSPACE_BRANCH_CHECK:
            return result

        try:
            paths = Paths(
                Path.cwd(),
                install_set=kwargs.get("install_set") or get_install_set_from_context(),
            )
            if not paths.settings.is_monorepo():
                check_all_on_same_branch(paths=paths, raise_error=True)
        except GitError as e:
            click.secho(e.args[0], fg="red", err=True)
        except FileNotFoundError:
            # This can happen for commands that run outside a multi workspace.
            pass

        return result

    # Replace the command's callback with our new wrapped version
    command_to_wrap.callback = new_wrapped_callback

    # Add the --verbose option to the command's parameters, if not already present
    # This ensures the `verbose` kwarg is available in new_wrapped_callback
    if not any(
        isinstance(p, click.Option) and p.name == "verbose"
        for p in command_to_wrap.params
    ):
        verbose_option = click.Option(
            ["--verbose"],
            is_flag=True,
            help="Enable verbose output.",
            # expose_value=True is default, making 'verbose' a kwarg to the callback
        )
        command_to_wrap.params.append(verbose_option)

    return command_to_wrap  # Return the modified command
