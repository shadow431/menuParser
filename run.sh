for menu in meals occasions desserts; do  docker run --rm --env-file .env --env-file .env-$menu menuparser:latest; done
