docker compose up --build -d
sleep 15
./scripts/db-migrate.sh
./scripts/ingest-osm.sh
./scripts/score-batch.sh