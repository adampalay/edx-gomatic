#!/usr/bin/env python
"""
Script to install pipelines that can deploy edxapp.
"""
import sys
from os import path

from gomatic import GitMaterial, PipelineMaterial

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position
from edxpipelines import utils
from edxpipelines.patterns import stages
from edxpipelines import constants
from edxpipelines.pipelines.script import pipeline_script


def install_pipelines(configurator, config):
    """
    Variables needed for this pipeline:
    - gocd_username
    - gocd_password
    - gocd_url
    - configuration_secure_repo
    - configuration_internal_repo
    - hipchat_token
    - github_private_key
    - aws_access_key_id
    - aws_secret_access_key
    - ec2_vpc_subnet_id
    - ec2_security_group_id
    - ec2_instance_profile_name
    - base_ami_id

    Optional variables:
    - configuration_secure_version
    - configuration_internal_version
    """
    pipeline = configurator.ensure_pipeline_group(config['pipeline_group'])\
                           .ensure_replacement_of_pipeline(config['pipeline_name'])

    # Example materials yaml
    # materials:
    #   - url: "https://github.com/edx/tubular"
    #     branch: "release"
    #     material_name: "tubular"
    #     polling: "True"
    #     destination_directory: "tubular"
    #     ignore_patterns:
    #     - '**/*'

    for material in config['materials']:
        pipeline.ensure_material(
            GitMaterial(
                url=material['url'],
                branch=material['branch'],
                material_name=material['material_name'],
                polling=material['polling'],
                destination_directory=material['destination_directory'],
                ignore_patterns=set(material['ignore_patterns'])
            )
        )

    # If no upstream pipelines exist, don't install them!
    for material in config.get('upstream_pipelines', []):
        pipeline.ensure_material(
            PipelineMaterial(
                pipeline_name=material['pipeline_name'],
                stage_name=material['stage_name'],
                material_name=material['material_name']
            )
        )

    #
    # Create the AMI-building stage.
    #
    stages.generate_launch_instance(
        pipeline,
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
        config['ec2_vpc_subnet_id'],
        config['ec2_security_group_id'],
        config['ec2_instance_profile_name'],
        config['base_ami_id'],
        manual_approval=not config.get('auto_run', False)
    )

    stages.generate_run_play(
        pipeline,
        'playbooks/edx-east/edxapp.yml',
        edp=utils.EDP(config['edx_environment'], config['edx_deployment'], config['play_name']),
        private_github_key=config['github_private_key'],
        app_repo=config['app_repo'],
        configuration_secure_dir='{}-secure'.format(config['edx_deployment']),
        configuration_internal_dir='{}-internal'.format(config['edx_deployment']),
        hipchat_token=config['hipchat_token'],
        hipchat_room='release',
        edx_platform_version='$GO_REVISION_EDX_PLATFORM',
        edx_platform_repo='$APP_REPO',
        configuration_version='$GO_REVISION_CONFIGURATION',
        edxapp_theme_source_repo=config['theme_url'],
        edxapp_theme_version='$GO_REVISION_EDX_THEME',
        edxapp_theme_name='$EDXAPP_THEME_NAME',
        disable_edx_services='true',
        COMMON_TAG_EC2_INSTANCE='true',
        cache_id='$GO_PIPELINE_COUNTER'
    )

    configuration_secure_repo = config['{}_configuration_secure_repo'.format(config['edx_deployment'])]
    configuration_internal_repo = config['{}_configuration_internal_repo'.format(config['edx_deployment'])]
    configuration_secure_version = '$GO_REVISION_{}_SECURE'.format(config['edx_deployment'].upper())
    configuration_internal_version = '$GO_REVISION_{}_INTERNAL'.format(config['edx_deployment'].upper())

    stages.generate_create_ami_from_instance(
        pipeline,
        edp=utils.EDP(config['edx_environment'], config['edx_deployment'], config['play_name']),
        app_repo=config['app_repo'],
        app_version='$GO_REVISION_EDX_PLATFORM',
        hipchat_token=config['hipchat_token'],
        hipchat_room='release pipeline',
        aws_access_key_id=config['aws_access_key_id'],
        aws_secret_access_key=config['aws_secret_access_key'],
        version_tags={
            'configuration': (config['configuration_url'], '$GO_REVISION_CONFIGURATION'),
            'configuration_secure': (configuration_secure_repo, configuration_secure_version),
            'configuration_internal': (configuration_internal_repo, configuration_internal_version),
            'edxapp_theme': (config['theme_url'], '$GO_REVISION_EDX_MICROSITE'),
        }
    )

    #
    # Create the DB migration running stage.
    #
    ansible_inventory_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.ANSIBLE_INVENTORY_FILENAME
    )
    instance_ssh_key_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.KEY_PEM_FILENAME
    )
    launch_info_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.LAUNCH_INSTANCE_FILENAME
    )
    for sub_app in ['cms', 'lms']:
        stages.generate_run_migrations(
            pipeline,
            db_migration_pass=config['db_migration_pass'],
            inventory_location=ansible_inventory_location,
            instance_key_location=instance_ssh_key_location,
            launch_info_location=launch_info_location,
            application_user=config['db_migration_user'],
            application_name=config['play_name'],
            application_path=config['application_path'],
            sub_application_name=sub_app
        )

    #
    # Create the stage to deploy the AMI.
    #
    ami_file_location = utils.ArtifactLocation(
        pipeline.name,
        constants.BUILD_AMI_STAGE_NAME,
        constants.BUILD_AMI_JOB_NAME,
        'ami.yml'
    )
    stages.generate_deploy_ami(
        pipeline,
        config['asgard_api_endpoints'],
        config['asgard_token'],
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
        ami_file_location,
        manual_approval=not config.get('auto_deploy_ami', False)
    )

    #
    # Create the stage to terminate the EC2 instance used to both build the AMI and run DB migrations.
    #
    instance_info_location = utils.ArtifactLocation(
        pipeline.name,
        constants.LAUNCH_INSTANCE_STAGE_NAME,
        constants.LAUNCH_INSTANCE_JOB_NAME,
        constants.LAUNCH_INSTANCE_FILENAME
    )
    stages.generate_terminate_instance(
        pipeline,
        instance_info_location,
        aws_access_key_id=config['aws_access_key_id'],
        aws_secret_access_key=config['aws_secret_access_key'],
        hipchat_token=config['hipchat_token'],
        runif='any'
    )

    #
    # Create the stage to configure the ASG dynamic scaling.
    #
    stages.generate_configure_dynamic_scaling(
        pipeline,
        config['aws_access_key_id'],
        config['aws_secret_access_key'],
        config['edx_environment'],
        manual_approval=not config.get('auto_configure_dynamic_scaling', False)
    )


if __name__ == "__main__":
    pipeline_script(install_pipelines)
