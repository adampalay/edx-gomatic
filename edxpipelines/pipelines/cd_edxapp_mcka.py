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


def install_pipelines(configurator, config):
    """

    :param configurator:
    :param config:
    :return:
    """
    generate_single_deployment_service_pipelines(
        configurator,
        config,
        'apros',
        EDX_APROS().url,
        deployment='mckinsey'
    )

if __name__ == '__main__':
    pipeline_script(install_pipelines)
