for menu in meals desserts occasions; do  docker run --rm --add-host=host.docker.internal:host-gateway --env-file .env-menuparser --env-file .env-$menu menuparser:20260421; done
