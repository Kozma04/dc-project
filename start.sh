conda init
conda activate dc_project
docker compose config
sudo docker compose up -d --build

echo "Showing messages..."
docker exec -it dc_mosquitto mosquitto_sub -h localhost -p 1883 -t 'home/#' -v
