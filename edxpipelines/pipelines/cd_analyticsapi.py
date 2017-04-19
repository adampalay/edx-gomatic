#!/usr/bin/env python
"""
Script to install pipelines that can deploy the analytics data API.
"""
import sys
from os import path

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position

from edxpipelines.patterns.pipelines import generate_service_pipelines_with_edge
from edxpipelines.pipelines.script import pipeline_script


def install_pipelines(configurator, config):
    """
    Generates pipelines used to deploy the analytics data API service to stage,
    loadtest, prod-edx, and prod-edge.
    """
    generate_service_pipelines_with_edge(
        configurator,
        config,
        'analytics_api',
        app_repo='https://github.com/edx/edx-analytics-data-api.git',
    )


if __name__ == '__main__':
    pipeline_script(install_pipelines, environments=('stage-edx', 'loadtest-edx', 'prod-edx', 'prod-edge'))
