#!/usr/bin/env python
"""
Script for installing pipelines used to deploy the discovery service.
"""
from os import path
import sys

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position

from edxpipelines.patterns.pipelines import generate_single_deployment_service_pipelines
from edxpipelines.pipelines.script import pipeline_script


def install_pipelines(configurator, config):
    """
    Generates pipelines used to deploy the discovery service to stage, loadtest, and prod.
    """
    generate_single_deployment_service_pipelines(
        configurator,
        config,
        'discovery',
        app_repo='https://github.com/edx/course-discovery.git',
    )


if __name__ == '__main__':
    pipeline_script(install_pipelines, environments=('stage-edx', 'loadtest-edx', 'prod-edx'))
