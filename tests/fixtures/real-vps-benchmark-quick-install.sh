#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_REPO="${VBP_RELEASE_REPO:-taotaoya-code/vps-benchmark-public}"
RELEASE_TAG="${VBP_RELEASE_TAG:-}"
ASSET_NAME="${VBP_ASSET_NAME:-vps-benchmark}"
INSTALL_DIR="${VBP_INSTALL_DIR:-/opt/vps-benchmark}"

ASSET_TGZ="${ASSET_NAME}.tar.gz"
ASSET_SHA256="${ASSET_NAME}.sha256"

TMP_DIR="$(mktemp -d /tmp/vbp-bootstrap.XXXXXX)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo '请使用 root 运行此脚本。' >&2
  exit 1
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

if ! need_cmd curl || ! need_cmd tar || ! need_cmd sha256sum; then
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y curl ca-certificates tar gzip coreutils
  else
    echo '当前仅支持 Debian / Ubuntu 自动安装依赖。' >&2
    exit 1
  fi
fi

if [[ -n "$RELEASE_TAG" ]]; then
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/download/${RELEASE_TAG}"
else
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/latest/download"
fi

echo "==> 下载安装包..."
curl -fL "${BASE_URL}/${ASSET_TGZ}" -o "${TMP_DIR}/${ASSET_TGZ}"

echo "==> 下载校验文件..."
curl -fL "${BASE_URL}/${ASSET_SHA256}" -o "${TMP_DIR}/${ASSET_SHA256}"

echo "==> 校验安装包..."
(
  cd "$TMP_DIR"
  sha256sum -c "$ASSET_SHA256"
)

UNPACK_DIR="${TMP_DIR}/unpack"
mkdir -p "$UNPACK_DIR"

echo "==> 解压安装包..."
tar -xzf "${TMP_DIR}/${ASSET_TGZ}" -C "$UNPACK_DIR"

if [[ ! -f "${UNPACK_DIR}/${ASSET_NAME}/install.sh" ]]; then
  echo "安装包结构错误：缺少 ${ASSET_NAME}/install.sh" >&2
  exit 1
fi

echo "==> 安装到 ${INSTALL_DIR} ..."
rm -rf "$INSTALL_DIR"
mkdir -p "$(dirname "$INSTALL_DIR")"
mv "${UNPACK_DIR}/${ASSET_NAME}" "$INSTALL_DIR"

chmod 700 "$INSTALL_DIR/install.sh" "$INSTALL_DIR/bootstrap.sh" "$INSTALL_DIR/main.sh"

echo "==> 启动安装脚本..."
exec bash "$INSTALL_DIR/install.sh"
