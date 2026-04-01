for menu in meals occasions desserts; do  docker run --rm --add-host=host.docker.internal:host-gateway --env-file .env --env-file .env-$menu menuparser:20260401; done
