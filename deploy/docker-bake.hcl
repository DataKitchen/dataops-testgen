variable "TESTGEN_VERSION" {}
variable "PUBLIC_RELEASE" {
  default = false
}

function "docker_repo" {
  params = []
  result = PUBLIC_RELEASE ? "datakitchen/dataops-testgen" : "datakitchen/dataops-testgen-qa"
}

target "testgen" {
  args = {
    TESTGEN_VERSION = "${TESTGEN_VERSION}"
  }
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = [
    "${docker_repo()}:v${TESTGEN_VERSION}",
    PUBLIC_RELEASE ? "${docker_repo()}:v${index(regex("([0-9]+.[0-9]+).[0-9]+", TESTGEN_VERSION), 0)}": "",
    PUBLIC_RELEASE ? "${docker_repo()}:v${index(regex("([0-9]+).[0-9]+.[0-9]+", TESTGEN_VERSION), 0)}": ""
  ]
}
