import click

from multi._version import __version__
from multi.add import add_cmd
from multi.branch import branch_cmd
from multi.cli_helpers import common_command_wrapper
from multi.collaborator import collaborator_cmd
from multi.convert_monorepo import convert_monorepo_cmd
from multi.doctor import doctor_cmd
from multi.git_run import git_cmd
from multi.git_set_branch import set_branch_cmd
from multi.hooks import (
    hooks_cmd,
    hooks_install_cmd,
    hooks_status_cmd,
    hooks_uninstall_cmd,
)
from multi.init import init_cmd
from multi.open import open_cmd
from multi.remove import remove_cmd
from multi.service import service_cmd
from multi.sync import sync_cmd
from multi.worktree import worktree_cmd


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"multi (multi-workspace) {__version__}")
    ctx.exit()


@click.group()
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Show the version and exit.",
)
def main():
    """VS Code Multi - Manage multiple Git repositories in VS Code.

    This CLI tool enables seamless work across multiple Git repositories within VS Code.
    Key features:
    - Synchronize Git operations across root and sub-repositories
    - Merge .vscode configurations (launch.json, tasks.json, settings.json)
    - Manage consistent branch states across all repositories
    """
    pass


main.add_command(common_command_wrapper(add_cmd))
main.add_command(collaborator_cmd)
main.add_command(common_command_wrapper(branch_cmd))
main.add_command(common_command_wrapper(set_branch_cmd))
main.add_command(common_command_wrapper(sync_cmd))
main.add_command(common_command_wrapper(git_cmd))
main.add_command(common_command_wrapper(init_cmd))
main.add_command(common_command_wrapper(doctor_cmd))
main.add_command(common_command_wrapper(convert_monorepo_cmd))
main.add_command(common_command_wrapper(remove_cmd))
main.add_command(worktree_cmd)
hooks_cmd.add_command(common_command_wrapper(hooks_install_cmd))
hooks_cmd.add_command(common_command_wrapper(hooks_status_cmd))
hooks_cmd.add_command(common_command_wrapper(hooks_uninstall_cmd))
main.add_command(hooks_cmd)
main.add_command(open_cmd)
main.add_command(service_cmd)

if __name__ == "__main__":
    main()
