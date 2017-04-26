#!/usr/bin/env python
"""
Build the pipeline system needed to deploy edxapp.
"""

import sys
from os import path

from gomatic import PipelineMaterial

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position
from edxpipelines import utils
from edxpipelines import constants
from edxpipelines.patterns.authz import Permission, ensure_permissions
from edxpipelines.patterns import edxapp
from edxpipelines.patterns.edxapp import (STAGE_EDX_EDXAPP, PROD_EDGE_EDXAPP, PROD_EDX_EDXAPP)
from edxpipelines.pipelines.script import pipeline_script
from edxpipelines.materials import (
    TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
    EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL
)


def install_pipelines(configurator, config):
    """
    Arguments:
        configurator (GoCdConfigurator)
        config (dict)
        env_config (dict)

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
    configurator.ensure_removal_of_pipeline_group('edxapp')
    configurator.ensure_removal_of_pipeline_group('edxapp_prod_deploys')
    edxapp_group = configurator.ensure_pipeline_group('edxapp')

    ensure_permissions(configurator, edxapp_group, Permission.OPERATE, ['edxapp-operator'])
    ensure_permissions(configurator, edxapp_group, Permission.VIEW, ['edxapp-operator'])

    edxapp_deploy_group = configurator.ensure_pipeline_group('edxapp_prod_deploys')

    ensure_permissions(configurator, edxapp_deploy_group, Permission.ADMINS, ['deploy'])
    ensure_permissions(configurator, edxapp_deploy_group, Permission.OPERATE, ['prod-deploy-operators'])
    ensure_permissions(configurator, edxapp_deploy_group, Permission.VIEW, ['prod-deploy-operators'])

    cut_branch = edxapp.make_release_candidate(
        edxapp_group,
        config,
    )
    cut_branch.set_label_template('${edx-platform[:7]}')

    prerelease_materials = edxapp.prerelease_materials(
        edxapp_group,
        config
    )

    prerelease_merge_artifact = utils.ArtifactLocation(
        prerelease_materials.name,
        constants.PRERELEASE_MATERIALS_STAGE_NAME,
        constants.PRERELEASE_MATERIALS_JOB_NAME,
        constants.PRIVATE_RC_FILENAME,
    )

    stage_b = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_group,
        [
            edxapp.generate_build_stages(
                app_repo=EDX_PLATFORM().url,
                edp=STAGE_EDX_EDXAPP,
                theme_url=EDX_MICROSITE().url,
                configuration_secure_repo=EDX_SECURE().url,
                configuration_internal_repo=EDX_INTERNAL().url,
                configuration_url=CONFIGURATION().url,
                prerelease_merge_artifact=prerelease_merge_artifact,
            ),
        ],
        config=config[edxapp.STAGE_EDX_EDXAPP],
        pipeline_name="STAGE_edxapp_B",
        ami_artifact=utils.ArtifactLocation(
            prerelease_materials.name,
            constants.BASE_AMI_SELECTION_STAGE_NAME,
            constants.BASE_AMI_SELECTION_EDP_JOB_NAME(STAGE_EDX_EDXAPP),
            constants.BASE_AMI_OVERRIDE_FILENAME,
        ),
        auto_run=True,
    )
    stage_b.set_label_template('${prerelease}')

    prod_edx_b = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.generate_build_stages(
                app_repo=EDX_PLATFORM().url,
                edp=PROD_EDX_EDXAPP,
                theme_url=EDX_MICROSITE().url,
                configuration_secure_repo=EDX_SECURE().url,
                configuration_internal_repo=EDX_INTERNAL().url,
                configuration_url=CONFIGURATION().url,
                prerelease_merge_artifact=prerelease_merge_artifact,
            ),
        ],
        config=config[edxapp.PROD_EDX_EDXAPP],
        pipeline_name="PROD_edx_edxapp_B",
        ami_artifact=utils.ArtifactLocation(
            prerelease_materials.name,
            constants.BASE_AMI_SELECTION_STAGE_NAME,
            constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDX_EDXAPP),
            constants.BASE_AMI_OVERRIDE_FILENAME,
        ),
        auto_run=True,
    )
    prod_edx_b.set_label_template('${prerelease}')

    prod_edge_b = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.generate_build_stages(
                app_repo=EDX_PLATFORM().url,
                edp=PROD_EDGE_EDXAPP,
                theme_url=EDX_MICROSITE().url,
                configuration_secure_repo=EDGE_SECURE().url,
                configuration_internal_repo=EDGE_INTERNAL().url,
                configuration_url=CONFIGURATION().url,
                prerelease_merge_artifact=prerelease_merge_artifact,
            ),
        ],
        config=config[edxapp.PROD_EDGE_EDXAPP],
        pipeline_name="PROD_edge_edxapp_B",
        ami_artifact=utils.ArtifactLocation(
            prerelease_materials.name,
            constants.BASE_AMI_SELECTION_STAGE_NAME,
            constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDGE_EDXAPP),
            constants.BASE_AMI_OVERRIDE_FILENAME,
        ),
        auto_run=True,
    )
    prod_edge_b.set_label_template('${prerelease}')

    for pipeline in (stage_b, prod_edx_b, prod_edge_b):
        pipeline.ensure_material(
            PipelineMaterial(
                pipeline_name=prerelease_materials.name,
                stage_name=constants.BASE_AMI_SELECTION_STAGE_NAME,
                material_name="prerelease",
            )
        )

    deployed_ami_pairs = [
        (
            utils.ArtifactLocation(
                "/".join([prerelease_materials.name, prod_edx_b.name]),
                constants.BASE_AMI_SELECTION_STAGE_NAME,
                ami_selection_job_name,
                constants.BASE_AMI_OVERRIDE_FILENAME,
            ),
            utils.ArtifactLocation(
                build_pipeline.name,
                constants.BUILD_AMI_STAGE_NAME,
                constants.BUILD_AMI_JOB_NAME,
                constants.BUILD_AMI_FILENAME,
            )
        ) for build_pipeline, ami_selection_job_name in [
            (prod_edx_b, constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDX_EDXAPP)),
            (prod_edge_b, constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDGE_EDXAPP))
        ]
    ]

    stage_md = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_group,
        stage_builders=[
            edxapp.generate_migrate_stages,
            edxapp.generate_deploy_stages(
                ami_pairs=deployed_ami_pairs,
                stage_deploy_pipeline_artifact=None,
                base_ami_artifact=utils.ArtifactLocation(
                    "/".join([prerelease_materials.name, prod_edx_b.name]),
                    constants.BASE_AMI_SELECTION_STAGE_NAME,
                    constants.BASE_AMI_SELECTION_EDP_JOB_NAME(STAGE_EDX_EDXAPP),
                    constants.BASE_AMI_OVERRIDE_FILENAME,
                ),
                head_ami_artifact=utils.ArtifactLocation(
                    stage_b.name,
                    constants.BUILD_AMI_STAGE_NAME,
                    constants.BUILD_AMI_JOB_NAME,
                    constants.BUILD_AMI_FILENAME,
                ),
                auto_deploy_ami=True,
            ),
        ],
        post_cleanup_builders=[
            edxapp.generate_e2e_test_stage,
        ],
        config=config[edxapp.STAGE_EDX_EDXAPP],
        pipeline_name="STAGE_edxapp_M-D",
        ami_artifact=utils.ArtifactLocation(
            stage_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME,
        ),
        auto_run=True,
    )
    stage_md.set_automatic_pipeline_locking()
    stage_md.set_label_template('${STAGE_edxapp_B_build}')

    # TODO
    # We should consider moving the publish_wiki_job (and perhaps the message_pr_job to their own pipelines, this would
    # allow the stage M-D pipeline to run independently of the prod_edx_b and prod_edge_b pipelines possibly unblocking
    # some builds.
    for build_stage in (stage_b, prod_edx_b, prod_edge_b):
        stage_md.ensure_material(
            PipelineMaterial(
                pipeline_name=build_stage.name,
                stage_name=constants.BUILD_AMI_STAGE_NAME,
                material_name="{}_build".format(build_stage.name),
            )
        )

    rollback_stage_db = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.rollback_database(edxapp.STAGE_EDX_EDXAPP, stage_md),
        ],
        config=config[edxapp.STAGE_EDX_EDXAPP],
        pipeline_name="stage_edxapp_Rollback_Migrations",
        ami_artifact=utils.ArtifactLocation(
            stage_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME
        ),
        auto_run=False,
        pre_launch_builders=[
            edxapp.armed_stage_builder,
        ],
    )
    rollback_stage_db.set_label_template('${deploy_pipeline}')

    manual_verification = edxapp.manual_verification(
        edxapp_deploy_group,
        config
    )
    manual_verification.set_label_template('${stage_ami_deploy}')

    manual_verification.ensure_material(
        PipelineMaterial(
            pipeline_name=stage_md.name,
            stage_name=constants.TERMINATE_INSTANCE_STAGE_NAME,
            material_name='stage_ami_deploy',
        )
    )

    manual_verification.ensure_material(
        PipelineMaterial(
            pipeline_name=prod_edx_b.name,
            stage_name=constants.BUILD_AMI_STAGE_NAME,
            material_name='PROD_edx_edxapp_ami_build',
        )
    )

    manual_verification.ensure_material(
        PipelineMaterial(
            pipeline_name=prod_edge_b.name,
            stage_name=constants.BUILD_AMI_STAGE_NAME,
            material_name='PROD_edge_edxapp_ami_build',
        )
    )

    release_advancer = edxapp.release_advancer(
        edxapp_deploy_group,
        config
    )
    release_advancer.set_label_template('${tubular[:7]}-${COUNT}')

    # When manually triggered in the pipeline above, the following two pipelines migrate/deploy
    # to the production EDX and EDGE environments.

    deployed_ami_pairs_prod = [
        (
            utils.ArtifactLocation(
                "/".join([prerelease_materials.name, build_pipeline.name, manual_verification.name]),
                constants.BASE_AMI_SELECTION_STAGE_NAME,
                ami_selection_job_name,
                constants.BASE_AMI_OVERRIDE_FILENAME,
            ),
            utils.ArtifactLocation(
                "/".join([build_pipeline.name, manual_verification.name]),
                constants.BUILD_AMI_STAGE_NAME,
                constants.BUILD_AMI_JOB_NAME,
                constants.BUILD_AMI_FILENAME,
            )
        ) for build_pipeline, ami_selection_job_name in [
            (prod_edx_b, constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDX_EDXAPP)),
            (prod_edge_b, constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDGE_EDXAPP))
        ]
    ]

    prod_edx_md = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.generate_migrate_stages,
            edxapp.generate_deploy_stages(
                ami_pairs=deployed_ami_pairs_prod,
                stage_deploy_pipeline_artifact=utils.ArtifactLocation(
                    "/".join([stage_md.name, manual_verification.name]),
                    constants.MESSAGE_PR_STAGE_NAME,
                    constants.PUBLISH_WIKI_JOB_NAME,
                    constants.RELEASE_WIKI_PAGE_ID_FILENAME,
                ),
                base_ami_artifact=utils.ArtifactLocation(
                    "/".join([prerelease_materials.name, prod_edx_b.name, manual_verification.name]),
                    constants.BASE_AMI_SELECTION_STAGE_NAME,
                    constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDX_EDXAPP),
                    constants.BASE_AMI_OVERRIDE_FILENAME,
                ),
                head_ami_artifact=utils.ArtifactLocation(
                    "/".join([prod_edx_b.name, stage_md.name, manual_verification.name]),
                    constants.BUILD_AMI_STAGE_NAME,
                    constants.BUILD_AMI_JOB_NAME,
                    constants.BUILD_AMI_FILENAME,
                ),
                auto_deploy_ami=True,
            )
        ],
        config=config[edxapp.PROD_EDX_EDXAPP],
        pipeline_name="PROD_edx_edxapp_M-D",
        ami_artifact=utils.ArtifactLocation(
            prod_edx_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME,
        ),
        auto_run=True,
    )
    prod_edx_md.set_label_template('${prod_release_gate}')

    prod_edge_md = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.generate_migrate_stages,
            edxapp.generate_deploy_stages(
                ami_pairs=deployed_ami_pairs_prod,
                stage_deploy_pipeline_artifact=utils.ArtifactLocation(
                    "/".join([stage_md.name, manual_verification.name]),
                    constants.MESSAGE_PR_STAGE_NAME,
                    constants.PUBLISH_WIKI_JOB_NAME,
                    constants.RELEASE_WIKI_PAGE_ID_FILENAME,
                ),
                base_ami_artifact=utils.ArtifactLocation(
                    "/".join([prerelease_materials.name, prod_edge_b.name, manual_verification.name]),
                    constants.BASE_AMI_SELECTION_STAGE_NAME,
                    constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDGE_EDXAPP),
                    constants.BASE_AMI_OVERRIDE_FILENAME,
                ),
                head_ami_artifact=utils.ArtifactLocation(
                    "/".join([prod_edge_b.name, stage_md.name, manual_verification.name]),
                    constants.BUILD_AMI_STAGE_NAME,
                    constants.BUILD_AMI_JOB_NAME,
                    constants.BUILD_AMI_FILENAME,
                ),
                auto_deploy_ami=True,
            )
        ],
        config=config[edxapp.PROD_EDGE_EDXAPP],
        pipeline_name="PROD_edge_edxapp_M-D",
        ami_artifact=utils.ArtifactLocation(
            "/".join([prod_edge_b.name, manual_verification.name]),
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME,
        ),
        auto_run=True,
    )
    prod_edge_md.set_label_template('${prod_release_gate}')

    for deploy in (prod_edx_md, prod_edge_md):
        deploy.ensure_material(
            PipelineMaterial(
                pipeline_name=manual_verification.name,
                stage_name=constants.MANUAL_VERIFICATION_STAGE_NAME,
                material_name="prod_release_gate",
            )
        )

    for pipeline in (stage_b, stage_md, prod_edx_b, prod_edx_md, prod_edge_b, prod_edge_md):
        for material in (
                TUBULAR, CONFIGURATION, EDX_PLATFORM, EDX_SECURE, EDGE_SECURE,
                EDX_MICROSITE, EDX_INTERNAL, EDGE_INTERNAL
        ):
            pipeline.ensure_material(material())

    rollback_edx = edxapp.rollback_asgs(
        edxapp_deploy_group=edxapp_deploy_group,
        pipeline_name='PROD_edx_edxapp_Rollback_latest',
        deploy_pipeline=prod_edx_md,
        config=config[edxapp.PROD_EDX_EDXAPP],
        ami_pairs=deployed_ami_pairs,
        stage_deploy_pipeline_artifact=utils.ArtifactLocation(
                    "/".join([stage_md.name, manual_verification.name, prod_edx_md.name]),
                    constants.MESSAGE_PR_STAGE_NAME,
                    constants.PUBLISH_WIKI_JOB_NAME,
                    constants.RELEASE_WIKI_PAGE_ID_FILENAME,
                ),
        base_ami_artifact=utils.ArtifactLocation(
            prerelease_materials.name,
            constants.BASE_AMI_SELECTION_STAGE_NAME,
            constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDX_EDXAPP),
            constants.BASE_AMI_OVERRIDE_FILENAME,
        ),
        head_ami_artifact=utils.ArtifactLocation(
            prod_edx_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME,
        ),
    )
    rollback_edx.set_label_template('${deploy_ami}')
    rollback_edge = edxapp.rollback_asgs(
        edxapp_deploy_group=edxapp_deploy_group,
        pipeline_name='PROD_edge_edxapp_Rollback_latest',
        deploy_pipeline=prod_edge_md,
        config=config[edxapp.PROD_EDGE_EDXAPP],
        ami_pairs=deployed_ami_pairs,
        stage_deploy_pipeline_artifact=utils.ArtifactLocation(
            "/".join([stage_md.name, manual_verification.name, prod_edge_md.name]),
            constants.MESSAGE_PR_STAGE_NAME,
            constants.PUBLISH_WIKI_JOB_NAME,
            constants.RELEASE_WIKI_PAGE_ID_FILENAME,
        ),
        base_ami_artifact=utils.ArtifactLocation(
            prerelease_materials.name,
            constants.BASE_AMI_SELECTION_STAGE_NAME,
            constants.BASE_AMI_SELECTION_EDP_JOB_NAME(PROD_EDGE_EDXAPP),
            constants.BASE_AMI_OVERRIDE_FILENAME,
        ),
        head_ami_artifact=utils.ArtifactLocation(
            prod_edge_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME,
        ),
    )
    rollback_edge.set_label_template('${deploy_ami}')

    rollback_edx.ensure_material(
        PipelineMaterial(prod_edx_md.name, constants.DEPLOY_AMI_STAGE_NAME, "deploy_ami")
    )

    rollback_edge.ensure_material(
        PipelineMaterial(prod_edge_md.name, constants.DEPLOY_AMI_STAGE_NAME, "deploy_ami")
    )

    rollback_edx_db = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.rollback_database(edxapp.PROD_EDX_EDXAPP, prod_edx_md),
        ],
        config=config[edxapp.PROD_EDX_EDXAPP],
        pipeline_name="PROD_edx_edxapp_Rollback_Migrations_latest",
        ami_artifact=utils.ArtifactLocation(
            prod_edx_b.name,
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME
        ),
        auto_run=False,
        pre_launch_builders=[
            edxapp.armed_stage_builder,
        ],
    )
    rollback_edx_db.set_label_template('${deploy_pipeline}')

    rollback_edge_db = edxapp.launch_and_terminate_subset_pipeline(
        edxapp_deploy_group,
        [
            edxapp.rollback_database(edxapp.PROD_EDGE_EDXAPP, prod_edge_md),
        ],
        config=config[edxapp.PROD_EDGE_EDXAPP],
        pipeline_name="PROD_edge_edxapp_Rollback_Migrations_latest",
        ami_artifact=utils.ArtifactLocation(
            "/".join([prod_edge_b.name, manual_verification.name, prod_edge_md.name]),
            constants.BUILD_AMI_STAGE_NAME,
            constants.BUILD_AMI_JOB_NAME,
            constants.BUILD_AMI_FILENAME
        ),
        auto_run=False,
        pre_launch_builders=[
            edxapp.armed_stage_builder,
        ],
    )
    rollback_edge_db.set_label_template('${deploy_pipeline}')

    deploy_artifact = utils.ArtifactLocation(
        prod_edx_md.name,
        constants.DEPLOY_AMI_STAGE_NAME,
        constants.DEPLOY_AMI_JOB_NAME,
        constants.DEPLOY_AMI_OUT_FILENAME,
    )

    merge_back = edxapp.merge_back_branches(
        edxapp_deploy_group,
        constants.BRANCH_CLEANUP_PIPELINE_NAME,
        deploy_artifact,
        prerelease_merge_artifact,
        config,
    )
    merge_back.set_label_template('${{deploy_pipeline_{}}}'.format(prod_edx_md.name))

    # Specify the upstream deploy pipeline materials for this branch-merging pipeline.
    for deploy_pipeline in (prod_edx_md, prod_edge_md):
        merge_back.ensure_material(
            PipelineMaterial(
                pipeline_name=deploy_pipeline.name,
                stage_name=constants.DEPLOY_AMI_STAGE_NAME,
                material_name='deploy_pipeline_{}'.format(deploy_pipeline.name),
            )
        )

    private_public_merge_sync = edxapp.private_public_merge_sync(
        edxapp_group,
        config,
    )
    private_public_merge_sync.set_label_template('${edx-platform-private[:7]}')


if __name__ == "__main__":
    pipeline_script(install_pipelines, environments=('stage-edx', 'prod-edx', 'prod-edge'))
