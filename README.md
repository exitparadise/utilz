# utilz
various utility scripts


### setenvs.sh
script to set your secrets in env vars

```
tee setenvs.sh <<EOF
export ELASTIC_API_KEY="<your elastic api key>"
EOF

. setenvs.sh
```

### elastic api key permissions

API Permissions for Elastic Agent/Fleet Managment

```
{
  "fleet-mgmt-api-permissions": {
    "cluster": [
      "manage_ilm",
      "write_fleet_secrets",
      "manage_pipeline",
      "manage_logstash_pipelines",
      "manage_ingest_pipelines",
      "manage_data_stream_global_retention"
    ],
    "indices": [
      {
        "names": [ "logs*", "metrics*" ],
        "privileges": [ "manage", "manage_ilm", "manage_data_stream_lifecycle" ],
        "field_security": {
          "grant": [ "*" ],
          "except": []
        },
        "allow_restricted_indices": true
      } 
    ],
    "applications": [
      {
        "application": "kibana-.kibana",
        "privileges": [ "feature_fleetv2.all", "feature_fleet.all" ],
        "resources": [ "*" ]
      }
    ],
    "run_as": [],
    "metadata": {},
    "transient_metadata": {
      "enabled": true
    }
  }
}

```
