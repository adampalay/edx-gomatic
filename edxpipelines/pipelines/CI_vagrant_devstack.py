#!/usr/bin/env python
"""
Script to install pipelines run CI for vagrant devstack
"""
import sys
from os import path

# Used to import edxpipelines files - since the module is not installed.
sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

# pylint: disable=wrong-import-position
from edxpipelines import constants
from edxpipelines.pipelines.script import pipeline_script
from edxpipelines.patterns.tasks import common
from edxpipelines.materials import E2E_TESTS, CONFIGURATION

from gomatic import GitMaterial

COURSE_TAR_FILE = 'AR-1000.tar.gz'
COURSE_NAME = 'AR-1000'
VAGRANT_NAME = 'default'

def install_pipelines(configurator, config):
    pipeline = configurator.ensure_pipeline_group("CI") \
        .ensure_replacement_of_pipeline("Vagrant_Devstack_CI")

    for material in (E2E_TESTS, CONFIGURATION):
        pipeline.ensure_material(material())

    # Make sure port is open for the e2e tests
    provision_devstack(pipeline)
    run_e2e(pipeline)


# add resource to job level
def provision_devstack(pipeline):
    build_stage = pipeline.ensure_stage("build_vagrant_devstack")
    build_job = build_stage.ensure_job("build_vagrant_devstack_job")

    # Install vbguest
    build_job.ensure_task(
        common.bash_task('vagrant plugin install vagrant-vbguest', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )

    # Bring up the image
    build_job.ensure_task(
        common.bash_task("CONFIGURATION_VERSION=jbarciauskas/fixes-to-vagrant-devstack-post-docker-merge OPENEDX_RELEASE=master vagrant up --provider virtualbox", working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )

    # Stop any running Vagrant image
    build_job.ensure_task(
        common.bash_task('vagrant halt', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )

    # Destroy any Vagrant image
    build_job.ensure_task(
        common.bash_task('vagrant destroy --force', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )

    # Remove .vagrant directory
    build_job.ensure_task(
        common.bash_task('rm -rf .vagrant', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )


def run_e2e(pipeline):
    # TODO: run the smoke tests
    test_stage = pipeline.ensure_stage('test_e2e_vagrant_devstack')
    test_job = test_stage.ensure_job('test_e2e_vagrant_devstack_job')
    test_job.ensure_resource('vagrant_devstack')
    test_job.ensure_environment_variables(
        {
            'BASIC_AUTH_USER': '',
            'BASIC_AUTH_PASSWORD': '',
            'USER_LOGIN_EMAIL': 'staff@example.com',
            'USER_LOGIN_PASSWORD': 'edx',
            'STUDIO_BASE_URL': 'http://localhost:8001/',
            'LMS_BASE_URL': 'http://localhost:8000/',
        }
    )

    # TODO Import the course
    test_job.ensure_task(
        common.bash_task('vagrant scp courses/{} {}:/edx/app/edxapp '.format(COURSE_TAR_FILE, VAGRANT_NAME), working_dir=constants.E2E_TESTS_DIR)
    )
    test_job.ensure_task(
        common.bash_task('''vagrant ssh -c 'tar -zxvf /edx/app/edxapp/{} --directory {}' '''.format(COURSE_TAR_FILE, COURSE_NAME),
                         working_dir=constants.E2E_TESTS_DIR)
    )
    test_job.ensure_task(
        common.bash_task('''vagrant ssh -c 'cd /edx/app/edxapp/edx-platform && sudo -u edxapp /edx/bin/python.edxapp ./manage.py cms --settings=devstack import /edx/app/edxapp {}' '''.format(COURSE_NAME),
                         working_dir=constants.E2E_TESTS_DIR)
    )

    test_job.ensure_task(
        common.bash_task(
            '''
            virtualenv -p python2.7 .python &&
            source .python/bin/activate &&
            pip install -r {}/requirements/requirements.txt
            '''.format(constants.E2E_TESTS_DIR))
    )

    # Install page objects
    test_job.ensure_task(
        common.bash_task('source ../.python/bin/activate && paver install_pages', working_dir=constants.E2E_TESTS_DIR)
    )
    
    # TODO run the tests
    test_job.ensure_task(
        common.bash_task('source ../.python/bin/activate && paver e2e_tests', working_dir=constants.E2E_TESTS_DIR)
    )


if __name__ == '__main__':
    pipeline_script(install_pipelines)
