# Overview

These are the Helm charts to install DataOps TestGen on a Kubernetes
environment. This README includes instructions for installing TestGen on a
minikube instance, including the application database engine, added by the
`testgen-services` charts. The application itself is installed by the
`testgen-app` charts. When installing on cloud, it's likely that the
application database will be provisioned by a cloud provider, and therefore
installing the `testgen-services` charts is not necessary.

# Preparing the Environment

Here are the instructions to create a local minikube cluster where DataOps
TestGen and its services will be installed. When deploying to a cloud /
production environment, this step should be adjusted accordingly.

Assuming that minikube is installed, the following command will create a
cluster named dk-testgen and configure the local kubectl tool to issue commands
against the cluster. When running helm commands against an existing cluster,
it's important to make sure that the kubectl tool is pointing to the correct
profile.

```shell
minikube start -p dk-testgen --namespace datakitchen
```

# Configuration

Whenever a helm command is used to generate manifests from templates
(`install`, `upgrade`), it will rely on pre-configured values to do so. Helm
provides a variety of ways to define these values. You can find the complete
configuration set that is also used as a default in each charts’ folder, in the
values.yaml file.

No additional configuration is recommended for the `testgen-services` charts.

The `testgen-app` charts require some configuration to be fine tuned. The best
way to do that is to save it in a values file, so that the same configuration
set can be easily used on the first install and future upgrades.

The following configuration is recommended for experimental installations, but
you're free to adjust it for your needs. The next installation steps assumes
that a file named tg-values.yaml exists with this configuration.

```yaml
testgen:

  # Password that will be assigned to the 'admin' user during the database preparation
  uiPassword: "admin"

  # Whether to trust the target database certificates.
  trustTargetDatabaseCertificate: true

  # Whether to run the SSL certificate verifications when connecting to DataOps Observability
  observabilityVerifySsl: false

image:

  # DataOps TestGen version to be installed / upgraded
  tag: v4.0
```

# Installing

The following command will install the required services for DataOps TestGen,
which currently is the Postgres database. This step is not needed when the
database is provisioned in a cloud environment.

```shell
helm install --create-namespace --wait testgen-services deploy/charts/testgen-services/
```

The following command will install the application. As part of the process, a
one-time database configuration will be automatically performed. Note that the
custom configuration values are being used.

```shell
helm install --wait -f tg-values.yaml testgen-app deploy/charts/testgen-app/
```

At this point you should have a fully functional instance of DataOps TestGen
installed. If you're looking to secure the UI password, you can delete it from
the values file.

# Accessing the Application

In order to use your TestGen instance, you have to use your web browser to
login to it. Your username will be admin and the password the one you
configured earlier.

It may be needed that you forward the application HTTP port in order to be able
to access it. This is especially necessary if you are using the docker driver
for minikube installed into a mac OS. The following command forwards the TesGen
“http” port to the host's 8501 port.

```shell
kubectl port-forward svc/testgen-app 8501:http
```

# Upgrading

When you already have a running instance of TestGen and want to upgrade it to a
newer version, you can do so without losing any data by running the
`upgrade-system-version` TestGen command from the target version's image. The
helm charts will do this automatically when you upgrade. You should edit your
values file to update the image tag value to the desired version, and then run
the following command.

```shell
helm upgrade --wait -f tg-values.yaml testgen-app deploy/charts/testgen-app/
```

# Uninstalling

The following commands will uninstall almost everything that was created
through the helm templates. It usually preserves data, which is helpful to
avoid unplanned data loss, but will likely break a future install attempt.

```shell
helm uninstall testgen-app
```

```shell
helm uninstall testgen-services
```

If you're uninstalling to re-install from scratch, and the data previously
generated can be purged, issue the following command to delete the database
volume so that the next installation will re-create and re-populate it
successfully.

```shell
kubectl delete pvc data-testgen-services-postgresql-0
```
