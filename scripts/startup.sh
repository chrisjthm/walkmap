docker compose up --build -d
sleep 10
./scripts/db-migrate.sh
./scripts/ingest-osm.sh
./scripts/score-batch.sh