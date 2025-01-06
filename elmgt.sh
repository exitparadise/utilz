#!/usr/bin/bash

APIKEY=${ELASTIC_API_KEY}
DEFAULT_HOST="elk1.talpas.dev" # change to your elastic server

POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      echo "  "
      echo "  mgmt.sh <action> [-o host] [-p] [-h] [host]"
      echo "     <action>	one of: nodes, shards, recovery, indices, drain, undrain"
      echo "     -o 		direct call to [host]"
      echo "     -p 		pretty"
      echo "     [host]		when action is drain, specify host to drain"
      echo " "
      exit 1
      ;;
    -o|--host)
      HOST="$2"
      shift # past argument
      shift # past value
      ;;
    -p|--prettty)
      PRETTY=YES
      shift # past argument
      ;;
    -*|--*)
      echo "Unknown option $1"
      exit 1
      ;;
    *)
      POSITIONAL_ARGS+=("$1") # save positional arg
      shift # past argument
      ;;
  esac
done

set -- "${POSITIONAL_ARGS[@]}" # restore positional parameters

if [ -z ${HOST} ]; then
    HOST=${DEFAULT_HOST}
fi

VERB=$1

if [ "${PRETTY}" = "YES" ]; then
    array=('nodes' 'shards' 'recovery' 'indices')
    if [[ " ${array[*]} " == *" ${VERB} "* ]]; then
        AUGMENT='?v&pretty'
    else 
        AUGMENT='?pretty'
    fi 
else 
    AUGMENT=''
fi

case "${VERB}" in
    "undrain")
        curl -k -XPUT https://{$HOST}:9200/_cluster/settings \
            -H "Authorization: ApiKey ${APIKEY}" \
            -H "Content-Type: application/json" \
            -d '{ "persistent": { "cluster.routing.allocation.exclude._name": "" } }'
        ;;
    "drain")
        if [ -z "${VAR}" ]; then
            echo "must supply a 3rd argument that is a hostname to drain" 
        else
            curl -k -XPUT https://{$HOST}:9200/_cluster/settings \
                -H "Authorization: ApiKey ${APIKEY}" \
                -H "Content-Type: application/json" \
                -d '{ "persistent": { "cluster.routing.allocation.exclude._name": "${AUGMENT}" } }'
        fi
        ;;
    "nodes")
        LOC='_cat/nodes'
        curl -sk -XGET https://${HOST}:9200/${LOC}${AUGMENT} -H "Authorization: ApiKey ${APIKEY}"
        ;;    
    "shards")
        LOC='_cat/shards'
        curl -sk -XGET https://${HOST}:9200/${LOC}${AUGMENT} -H "Authorization: ApiKey ${APIKEY}"
        ;;
    "health")
        LOC='_cluster/health?pretty'
        curl -sk -XGET https://${HOST}:9200/${LOC}${AUGMENT} -H "Authorization: ApiKey ${APIKEY}"
        ;;
    "recovery")
        LOC='_cat/recovery?v'
        curl -sk -XGET https://${HOST}:9200/${LOC}${AUGMENT} -H "Authorization: ApiKey ${APIKEY}"
        ;;
    *)
        echo "${VERB} is not a valid command" 
        ;;
esac


