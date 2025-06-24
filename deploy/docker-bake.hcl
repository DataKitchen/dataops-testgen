variable "TESTGEN_LABELS" {}
variable "TESTGEN_BASE_LABEL" {}
variable "TESTGEN_VERSION" {}
variable "TESTGEN_DOCKER_HUB_REPO" {
  default = "datakitchen/dataops-testgen"
}
variable "TESTGEN_SUPPORT_EMAIL" {
  default = "open-source-support@datakitchen.io"
}

target "testgen-release" {
  args = {
    TESTGEN_VERSION = "${TESTGEN_VERSION}"
    TESTGEN_BASE_LABEL = "${TESTGEN_BASE_LABEL}"
    TESTGEN_DOCKER_HUB_REPO = "${TESTGEN_DOCKER_HUB_REPO}"
    TESTGEN_SUPPORT_EMAIL = "${TESTGEN_SUPPORT_EMAIL}"
  }
  context = "."
  dockerfile = "deploy/testgen.dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = formatlist("datakitchen/dataops-testgen:%s", split(" ", TESTGEN_LABELS))
  attest = [
    {
      type = "provenance",
      mode = "max",
    },
    {
      type = "sbom",
    }
  ]
}

target "testgen-qa" {
  args = {
    TESTGEN_VERSION = "${TESTGEN_VERSION}"
    TESTGEN_BASE_LABEL = "${TESTGEN_BASE_LABEL}"
    TESTGEN_DOCKER_HUB_REPO = "${TESTGEN_DOCKER_HUB_REPO}"
    TESTGEN_SUPPORT_EMAIL = "${TESTGEN_SUPPORT_EMAIL}"
  }
  context = "."
  dockerfile = "deploy/testgen.dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = [format("datakitchen/dataops-testgen-qa:%s", index(split(" ", TESTGEN_LABELS), 0))]
}

target "testgen-base" {
  context = "."
  dockerfile = "deploy/testgen-base.dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = formatlist("datakitchen/dataops-testgen-base:%s", split(" ", TESTGEN_LABELS))
}
