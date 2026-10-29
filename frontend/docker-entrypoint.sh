#!/bin/sh
set -eu

file_bytes="${MAX_FILE_SIZE_BYTES:-26214400}"
case "$file_bytes" in
    ''|0*|*[!0-9]*)
        echo "MAX_FILE_SIZE_BYTES must be a positive decimal integer without leading zeroes" >&2
        exit 1
        ;;
esac
request_bytes=$((file_bytes + 65536))
if [ "$request_bytes" -le "$file_bytes" ]; then
    echo "MAX_FILE_SIZE_BYTES is too large" >&2
    exit 1
fi

sed "s/__MAX_REQUEST_BYTES__/$request_bytes/g" /etc/nginx/homesphere.conf.template > /tmp/homesphere-nginx.conf
exec nginx -c /tmp/homesphere-nginx.conf -g 'daemon off;'
