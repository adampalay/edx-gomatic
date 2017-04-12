#!/usr/bin/env python
"""
Script to install pipeline that can build ora2 sandboxes.
"""

import sys
from os import path

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position
from edxpipelines.patterns import tasks
from edxpipelines.materials import (TUBULAR, EDX_ORA2)
from edxpipelines import constants
from edxpipelines.pipelines.script import pipeline_script


def install_pipelines(configurator, config):
    """
    Variables needed for this pipeline:
    - gocd_username
    - gocd_password
    - gocd_url
    - configuration_secure_rep
    - jenkins_user_token
    - jenkins_job_token
    """

    pipeline = configurator.ensure_pipeline_group(constants.ORA2_PIPELINE_GROUP_NAME) \
                           .ensure_replacement_of_pipeline(constants.BUILD_ORA2_SANDBOX_PIPELINE_NAME) \
                           .set_timer('0 30 9 * * ?')

    for material in (TUBULAR, EDX_ORA2):
        pipeline.ensure_material(material())

    pipeline.ensure_environment_variables(
        {
            'DNS_NAME': 'ora2',
            'NAME_TAG': 'ora2',
            'EDXAPP_VERSION': 'master',
            'ORA2_VERSION': 'master',
            'CONFIGURATION_VERSION': 'master',
            'CONFIGURATION_SOURCE_REPO': 'https://github.com/edx/configuration.git',
            'CONFIGURATION_SECURE_VERSION': 'master',
            'CONFIGURATION_INTERNAL_VERSION': 'master',
            'NOTIFY_ON_FAILURE': 'educator-dev@edx.org'
        }
    )

    pipeline.ensure_unencrypted_secure_environment_variables(
        {
            'JENKINS_USER_TOKEN': config['jenkins_user_token'],
            'JENKINS_JOB_TOKEN': config['jenkins_job_token']
        }
    )

    # Create the Create Sandbox stage, job, and task
    jenkins_create_ora2_sandbox_stage = pipeline.ensure_stage(
        constants.CREATE_ORA2_SANDBOX_STAGE_NAME
    )
    jenkins_create_ora2_sandbox_job = jenkins_create_ora2_sandbox_stage.ensure_job(
        constants.CREATE_ORA2_SANDBOX_JOB_NAME
    )
    tasks.generate_package_install(jenkins_create_ora2_sandbox_job, 'tubular')

    # Keys need to be lower case for this job to use them
    create_ora2_sandbox_jenkins_params = {
        'dns_name': '$DNS_NAME',
        'name_tag': '$NAME_TAG',
        'edxapp_version': '$EDXAPP_VERSION',
        'configuration_version': '$CONFIGURATION_VERSION',
        'configuration_source_repo': '$CONFIGURATION_SOURCE_REPO',
        'configuration_secure_version': '$CONFIGURATION_SECURE_VERSION',
        'configuration_internal_version': '$CONFIGURATION_INTERNAL_VERSION',
        'basic_auth': 'false'
    }
    jenkins_timeout = 75 * 60
    jenkins_create_ora2_sandbox_job.timeout = str(jenkins_timeout + 60)
    tasks.trigger_jenkins_build(
        jenkins_create_ora2_sandbox_job,
        constants.ORA2_JENKINS_URL,
        constants.ORA2_JENKINS_USER_NAME,
        constants.CREATE_ORA2_SANDBOX_JENKINS_JOB_NAME,
        create_ora2_sandbox_jenkins_params,
        timeout=jenkins_timeout
    )

    # Create the Set Ora2 Version stage, job, and task
    jenkins_set_ora2_version_stage = pipeline.ensure_stage(
        constants.SET_ORA2_VERSION_STAGE_NAME
    )
    jenkins_set_ora2_version_job = jenkins_set_ora2_version_stage.ensure_job(
        constants.SET_ORA2_VERSION_JOB_NAME
    )
    tasks.generate_package_install(jenkins_set_ora2_version_job, 'tubular')
    # Keys need to be upper case for this job to use them
    set_ora2_version_jenkins_params = {
        'SANDBOX_HOST': '${DNS_NAME}.sandbox.edx.org',  # uses a different variable name for set version
        'ORA2_VERSION': '$ORA2_VERSION',
        'NOTIFY_ON_FAILURE': '$NOTIFY_ON_FAILURE'
    }
    tasks.trigger_jenkins_build(
        jenkins_set_ora2_version_job,
        constants.ORA2_JENKINS_URL,
        constants.ORA2_JENKINS_USER_NAME,
        constants.SET_ORA2_VERSION_JENKINS_JOB_NAME,
        set_ora2_version_jenkins_params
    )

    # Create the Ora2 Add Course to Sandbox stage, job, and task
    jenkins_add_course_to_ora2_stage = pipeline.ensure_stage(
        constants.ADD_COURSE_TO_ORA2_STAGE_NAME
    )
    jenkins_add_course_to_ora2_job = jenkins_add_course_to_ora2_stage.ensure_job(
        constants.ADD_COURSE_TO_ORA2_JOB_NAME
    )
    tasks.generate_package_install(jenkins_add_course_to_ora2_job, 'tubular')
    # Keys need to be upper case for this job to use them
    add_course_to_ora2_jenkins_params = {
        'SANDBOX_BASE': '$DNS_NAME',
    }
    tasks.trigger_jenkins_build(
        jenkins_add_course_to_ora2_job,
        constants.ORA2_JENKINS_URL,
        constants.ORA2_JENKINS_USER_NAME,
        constants.ADD_COURSE_TO_ORA2_JENKINS_JOB_NAME,
        add_course_to_ora2_jenkins_params
    )

    # Create the Enable Auto Auth stage, job, and task
    jenkins_enable_auto_auth_stage = pipeline.ensure_stage(
        constants.ENABLE_AUTO_AUTH_STAGE_NAME
    )
    jenkins_enable_auto_auth_job = jenkins_enable_auto_auth_stage.ensure_job(
        constants.ENABLE_AUTO_AUTH_JOB_NAME
    )
    tasks.generate_package_install(jenkins_enable_auto_auth_job, 'tubular')
    # Keys need to be upper case for this job to use them
    enable_auto_auth_jenkins_params = {
        'SANDBOX_BASE': '$DNS_NAME'
    }
    tasks.trigger_jenkins_build(
        jenkins_enable_auto_auth_job,
        constants.ORA2_JENKINS_URL,
        constants.ORA2_JENKINS_USER_NAME,
        constants.ENABLE_AUTO_AUTH_JENKINS_JOB_NAME,
        enable_auto_auth_jenkins_params
    )

    # Create the Ora2 Run Tests stage, job, and task
    jenkins_run_ora2_tests_stage = pipeline.ensure_stage(
        constants.RUN_ORA2_TESTS_STAGE_NAME
    )
    jenkins_run_ora2_tests_job = jenkins_run_ora2_tests_stage.ensure_job(
        constants.RUN_ORA2_TESTS_JOB_NAME
    )
    tasks.generate_package_install(jenkins_run_ora2_tests_job, 'tubular')
    # Keys need to be upper case for this job to use them
    run_ora2_tests_jenkins_params = {
        'TEST_HOST': '${DNS_NAME}.sandbox.edx.org',
        'BRANCH': '$ORA2_VERSION',
        'SLEEP_TIME': 300
    }
    jenkins_timeout = 75 * 60
    tasks.trigger_jenkins_build(
        jenkins_run_ora2_tests_job,
        constants.ORA2_JENKINS_URL,
        constants.ORA2_JENKINS_USER_NAME,
        constants.RUN_ORA2_TESTS_JENKINS_JOB_NAME,
        run_ora2_tests_jenkins_params,
        timeout=jenkins_timeout
    )

if __name__ == "__main__":
    pipeline_script(install_pipelines)
