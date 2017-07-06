"""
A standard interface for pipeline update scripts.
"""

import click
from gomatic import GoCdConfigurator, HostRestClient

import edxpipelines.utils as utils


def pipeline_script(install_pipelines, environments=(), edps=()):
    """
    Convert a function into a pipeline system creation script.
    """
    @click.command(help=install_pipelines.__doc__)
    @click.option(
        '--save-config', 'save_config_locally',
        envvar='SAVE_CONFIG',
        help='Save the pipeline configuration xml locally.',
        required=False,
        default=False,
        is_flag=True
    )
    @click.option(
        '--dry-run',
        envvar='DRY_RUN',
        help='Perform a dry run of the pipeline installation, and save the pre/post xml configurations locally.',
        required=False,
        default=False,
        is_flag=True
    )
    @click.option(
        '--variable_file', 'variable_files',
        multiple=True,
        help='Path to yaml variable file with a dictionary of key/value pairs to be used as variables in the script.',
        required=False,
        default=[]
    )
    @click.option(
        '--env-variable-file', 'env_variable_files',
        multiple=True,
        type=(
            click.Choice(set(environments) | set(edp.environment for edp in edps)),
            click.Path(dir_okay=False, exists=True)
        ),
        help='An environment, and a variable file that applies only to that environment',
        required=False,
        default=[],
    )
    @click.option(
        '--env-deploy-variable-file', 'env_deploy_variable_files',
        multiple=True,
        type=(
            click.Choice(set(environments) | set(
                '{0.environment}-{0.deployment}'.format(edp)
                for edp in edps
            )),
            click.Path(dir_okay=False, exists=True)
        ),
        help='An environment-deployment, and a variable file that applies only to that environment',
        required=False,
        default=[],
    )
    @click.option(
        '-e', '--variable', 'cmd_line_vars',
        multiple=True,
        help='Key/value used as a replacement variable in this script, as in KEY=VALUE.',
        required=False,
        type=(str, str),
        nargs=2,
        default={}
    )
    def cli(  # pylint: disable=missing-docstring
            save_config_locally, dry_run, variable_files,
            env_variable_files, env_deploy_variable_files, cmd_line_vars
    ):
        config = utils.ConfigMerger(variable_files, env_variable_files, env_deploy_variable_files, cmd_line_vars)

        # Create the pipeline
        # rest_client = HostRestClient(config['gocd_url'])
        # rest_client.get('')
        # payload = {
        #     'j_username': config['gocd_username'],
        #     'j_password': config['gocd_password']
        # }
        # rest_client.post('', payload)
        # configurator = GoCdConfigurator(rest_client)

        configurator = GoCdConfigurator(HostRestClient(
            config['gocd_url'],
            config['gocd_username'],
            config['gocd_password'],
            ssl=True
        ))
        return_val = install_pipelines(configurator, config)
        configurator.save_updated_config(save_config_locally=save_config_locally, dry_run=dry_run)
        return return_val

    cli()  # pylint: disable=no-value-for-parameter
