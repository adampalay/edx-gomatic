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
    cleanup(pipeline)


# add resource to job level
def provision_devstack(pipeline):
    build_stage = pipeline.ensure_stage("build_vagrant_devstack")
    build_job = build_stage.ensure_job("build_vagrant_devstack_job")

    # Install vbguest
    build_job.ensure_task(
        common.bash_task('vagrant plugin install vagrant-vbguest', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR),
        common.bash_task("vagrant provision", working_dir=constants.PUBLIC_CONFIGURATION_DIR),
    )

    # Bring up the image
    build_job.ensure_task(
        common.bash_task("OPENEDX_RELEASE=master vagrant up --provider virtualbox", working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
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
            'COURSE_ORG': 'AR',
            'COURSE_NUMBER': '1000',
            'COURSE_RUN': '',
            'COURSE_DISPLAY_NAME': '',
            'USER_LOGIN_EMAIL': 'staff@example.com',
            'USER_LOGIN_PASSWORD': 'edx',
            'STUDIO_BASE_URL': 'http://localhost:8001/',
            'LMS_BASE_URL': 'http://localhost:8000/',
            'ACCESS_TOKEN': '',
            'STAFF_USER_EMAIL': 'bbeggs@edx.org',
            'GLOBAL_PASSWORD':'',
        }
    )

    # TODO Import the course
    test_job.ensure_task(
        common.bash_task('vagrant plugin install vagrant-scp', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task('vagrant scp ../../../../{2}/courses/{0} {1}:/tmp/ '.format(COURSE_TAR_FILE, VAGRANT_NAME, constants.E2E_TESTS_DIR), working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task('''vagrant ssh -c 'mkdir -p /tmp/AR-1000 && tar -zxvf /tmp/{} -C /tmp/{}' '''.format(COURSE_TAR_FILE, COURSE_NAME),
                         working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task('''vagrant ssh -c 'cd /edx/app/edxapp/edx-platform && sudo -u edxapp /edx/bin/python.edxapp ./manage.py cms --settings=devstack import /tmp/{}' '''.format(COURSE_NAME),
                         working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task(
            '''vagrant ssh -c 'sudo -u edxapp -c if [ ! -f ~/.profile ]; then ln -s ~/.bashrc ~/.profile; fi' ''',
            working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task(
            '''vagrant ssh -c 'cd /edx/app/edxapp/edx-platform && sudo -u edxapp paver devstack --fast cms' ''',
            working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )
    test_job.ensure_task(
        common.bash_task(
            '''vagrant ssh -c 'cd /edx/app/edxapp/edx-platform && sudo -u edxapp paver devstack --fast lms' ''',
            working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR)
    )


    test_job.ensure_task(
        common.bash_task(
            '''
            virtualenv -p python2.7 .python &&
            source .python/bin/activate &&
            pwd &&
            ls -alh {0}/requirements &&
            pip install -r {0}/requirements/base.txt
            '''.format(constants.E2E_TESTS_DIR))
    )

    # Install page objects
    test_job.ensure_task(
        common.bash_task('source ../.python/bin/activate && paver install_pages', working_dir=constants.E2E_TESTS_DIR)
    )
    
    # TODO run the tests
    test_job.ensure_task(
        common.bash_task('source ../.python/bin/activate && paver e2e_test', working_dir=constants.E2E_TESTS_DIR)
    )

    # cleanup
    # test_job.ensure_task(
    #     common.bash_task()
    # )


def cleanup(pipeline):
    stage = pipeline.ensure_stage('vagrant_cleanup_stage')
    cleanup_job = stage.ensure_job('vagrant_cleanup_job')

    # Stop any running Vagrant image
    cleanup_job.ensure_task(
        common.bash_task('vagrant halt', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )

    # Destroy any Vagrant image
    cleanup_job.ensure_task(
        common.bash_task('vagrant destroy --force', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )

    # Remove .vagrant directory
    cleanup_job.ensure_task(
        common.bash_task('rm -rf .vagrant', working_dir=constants.PUBLIC_CONFIGURATION_DEVSTACK_DIR, runif='any')
    )

if __name__ == '__main__':
    pipeline_script(install_pipelines)
