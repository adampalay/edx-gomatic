from edxpipelines.patterns.apros import \
    generate_single_deployment_service_pipelines
from edxpipelines.pipelines.script import pipeline_script


def install_pipelines(configurator, config):
    generate_single_deployment_service_pipelines(configurator, config,
                                                 'apros')

if __name__ == '__main__':
    pipeline_script(install_pipelines)
