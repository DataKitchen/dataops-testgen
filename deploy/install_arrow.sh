#!/usr/bin/env bash

export ARROW_VERSION=18.0.0
export ARROW_SHA256=9c473f2c9914c59ab571761c9497cf0e5cfd3ea335f7782ccc6121f5cb99ae9b

export ARROW_HOME=/dk
export PARQUET_HOME=/dk

mkdir /arrow

# Obtaining and expanding Arrow
wget -q https://github.com/apache/arrow/archive/apache-arrow-${ARROW_VERSION}.tar.gz -O /tmp/apache-arrow.tar.gz
echo "${ARROW_SHA256} *apache-arrow.tar.gz" | sha256sum /tmp/apache-arrow.tar.gz
tar -xvf /tmp/apache-arrow.tar.gz -C /arrow --strip-components 1

pushd /arrow/cpp

# Configure the build using CMake
cmake --preset ninja-release-python

# Configuring cmake for ARM only
if [ "$(uname -m)" = "arm64" ] || [ "$(uname -m)" = "aarch64" ]; then
  cmake -DCMAKE_CXX_FLAGS="-march=armv8-a"
fi

# Pre-fetch dependencies without building
cmake --build . --target re2_ep -- -j2 || true

# Apply the patch to re2 after the dependencies are fetched but before the build
pushd re2_ep-prefix/src/re2_ep

cat <<EOF | patch -p1
diff --git a/util/pcre.h b/util/pcre.h
--- a/util/pcre.h
+++ b/util/pcre.h
@@ -166,0 +166,1 @@
+#include <cstdint>
EOF

popd

# Finish processing dependencies after patch
cmake --build . --target re2_ep -- -j2

# Continue with the build and install Apache Arrow
cmake --build . --target install

popd

rm -rf /arrow /tmp/apache-arrow.tar.gz
