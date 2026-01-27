#!/usr/bin/env sh

# From: https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server
# modifications: added --non-interactive and --no-cache flags, removed sudo, added aarch64 as an alias for arm64,
#                added certificate installation, isolated folder, replaced gpg --verify with gpgv

architecture="unsupported"

case "$(uname -m)" in
  x86_64)
    architecture="amd64"
    ;;
  arm64|aarch64)
    architecture="arm64"
    ;;
esac

if [ "unsupported" = "$architecture" ]; then
  echo "Alpine architecture $(uname -m) is not currently supported."
  exit 1
fi

(
  set -e
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  cd "$tmpdir"

  # Recent Alpine versions lacks the Microsoft certificate chain, so we download and install it manually
  curl -fsSL -o cert.crt https://www.microsoft.com/pkiops/certs/Microsoft%20TLS%20G2%20ECC%20CA%20OCSP%2002.crt
  openssl x509 -inform DER -in cert.crt -out /usr/local/share/ca-certificates/microsoft_tls_g2_ecc_ocsp_02.pem
  update-ca-certificates

  # Download the desired packages
  curl -O https://download.microsoft.com/download/9dcab408-e0d4-4571-a81a-5a0951e3445f/msodbcsql18_18.6.1.1-1_$architecture.apk
  curl -O https://download.microsoft.com/download/b60bb8b6-d398-4819-9950-2e30cf725fb0/mssql-tools18_18.6.1.1-1_$architecture.apk

  # Verify signature, if 'gpg' is missing install it using 'apk add gnupg':
  curl -O https://download.microsoft.com/download/9dcab408-e0d4-4571-a81a-5a0951e3445f/msodbcsql18_18.6.1.1-1_$architecture.sig
  curl -O https://download.microsoft.com/download/b60bb8b6-d398-4819-9950-2e30cf725fb0/mssql-tools18_18.6.1.1-1_$architecture.sig

  curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
  gpgv --keyring ./microsoft.gpg msodbcsql18_*.sig msodbcsql18_*.apk
  gpgv --keyring ./microsoft.gpg mssql-tools18_*.sig mssql-tools18_*.apk

  # Install the packages
  apk add --no-cache --allow-untrusted msodbcsql18_18.6.1.1-1_$architecture.apk
  apk add --no-cache --allow-untrusted mssql-tools18_18.6.1.1-1_$architecture.apk
)
