"""
Deployment pipeline for McKinsey Academy.
"""
import sys
from os import path

sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

from edxpipelines.patterns.apros import generate_deployment_service_pipelines
from edxpipelines.pipelines.script import pipeline_script




def install_pipelines(configurator, config):
    """

    :param configurator:
    :param config:
    :return:
    """
    generate_deployment_service_pipelines(configurator, config, 'apros')

if __name__ == '__main__':
    pipeline_script(install_pipelines)
