"""
Deployment pipeline for McKinsey Academy.
"""
import sys
from os import path

# pylint: disable=wrong-import-position
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

from edxpipelines.pipelines.script import pipeline_script
from edxpipelines.patterns.pipelines import generate_single_deployment_service_pipelines
from edxpipelines.materials import EDX_APROS
from edxpipelines.utils import MigrationAppInfo


def install_pipelines(configurator, config):
    """

    :param configurator:
    :param config:
    :return:
    """
    generate_single_deployment_service_pipelines(
        configurator,
        config,
        'mckinseyapros',
        EDX_APROS().url,
        deployment='mckinsey',
        additional_migrations=[
            MigrationAppInfo('edx-platform', '/edx/app/edxapp/', 'cms'),
            MigrationAppInfo('edx-platform', '/edx/app/edxapp/', 'lms'),
        ],
        # Just specify the correct play to run. Since there is no {} in the string, the substitution that happens
        # later will just leave this string as is invoking the correct play. #dirtyhack #non_standard_play_name.
        # John, I know you are reading this and cringing, I didn't want to rename the role
        # and break the other automation.
        playbook_path_tpl='../ansible-private/roles/mckinsey_apros.yml'.format
    )

if __name__ == '__main__':
    pipeline_script(install_pipelines)
