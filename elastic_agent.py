#!/usr/bin/env python
#

import argparse, requests, json, os, sys, re

requests.packages.urllib3.disable_warnings() 

parser = argparse.ArgumentParser(description="Elastic Agent Management Utility")

subparsers = parser.add_subparsers(dest="cmd")
parser_template = subparsers.add_parser("template", help="index template actions")
parser_template.add_argument("namespace", help="the namespace we are working on") 
parser_template.add_argument("action", choices=["list","details","init","update"])
parser_template.add_argument("source", nargs="?", help="when action is 'update' or 'describe', specify agent policy")
parser_template.add_argument("-l", "--lifecycle-policy", help="when action is 'update', add this policy. 'none' means remove policy")
parser_template.add_argument("-d", "--retention-days", type=int, help="when action is 'init' or 'update', number of retention days to apply")

parser_agent = subparsers.add_parser("agent", help="agent policy actions")
parser_agent.add_argument("namespace", help='the namespace we are working on') 
parser_agent.add_argument("action", choices=["list","details","describe","copy"])
parser_agent.add_argument("source", nargs="?", help="when action is 'copy' or 'describe', specify agent policy")
parser_agent.add_argument("-f", "--full", action="store_true", help="when action is 'describe', enable full output")

args=parser.parse_args()

VERIFY=False
ELASTIC_HOST="elastic-api:9200"
KIBANA_HOST="kibana-api:5601"
API_KEY=os.environ.get('ELASTIC_API_KEY')

class txt:
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'

class dict_append:
    def __init__(self, target):
        self.target = target
    def __getitem__(self, key):
        return dict_append(self.target.setdefault(key, {}))
    def __setitem__(self, key, value):
        self.target[key] = value

def main():
    WARN={}
    if args.cmd == 'agent':
        if args.action in ('list', 'details'):
            pol = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.namespace:{args.namespace}")
            for policy in pol['items']:
                if policy['namespace'] == args.namespace:
                    print(txt.BOLD + f"{policy['name']}" + txt.END + f" agents: {policy['agents']}")
                    if args.action == 'details':
                        full = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{policy['id']}/full")
                        print("    integrations:")
                        for input in full['item']['inputs']:
                            print(f"    - {input['name']} - {input['type']}")
        elif args.action == 'copy':
            if not args.source:
                sys.exit("copy must specify source (an agent policy name)") 
            else:
                p = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.name:{args.source}")
                policy = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{p['items'][0]['id']}")
                new_name = re.sub("^[^-]+",args.namespace,args.source)

                print(f"copy {policy['item']['name']}/{policy['item']['id']} to {new_name}")

                (new_policy,packages) = agent_policy_rename(policy['item'], args.namespace, new_name)
                new_policy_def = post_elastic(KIBANA_HOST,f"api/fleet/agent_policies",new_policy)
                print(f" - new policy ID: {new_policy_def['item']['id']}")
                
                for pkg in packages:
                   pkg['policy_id'] = new_policy_def['item']['id']
                   ### ttalpas
                   if pkg['package']['name'] == 'mysql':
                       del pkg['secret_references']
                       WARN['P'] = "[!P] = edit integration through the UI to re-add passwords"
                       W =  txt.BOLD + "[!P]" + txt.END
                       for input in pkg['inputs']:
                           if input['type'] == 'mysql/metrics':
                               input['vars']['password']['value'] = ""
                               for stream in input['streams']:
                                   try:
                                       del stream['compiled_stream'] 
                                   except:
                                       pass
                   else:
                       W = ""

                   pkgadd = post_elastic(KIBANA_HOST,f"api/fleet/package_policies",pkg)
                   print(f" - add integration: {pkgadd['item']['name']}/{pkgadd['item']['id']} {W}")
                print("Done!")

        elif args.action == 'describe':
            if not args.source:
                sys.exit("describe must specify a source") 
            else:
                p = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.name:{args.source}")
                if args.full:
                    policy = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{p['items'][0]['id']}/full")
                else:
                    try:
                        policy = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{p['items'][0]['id']}")
                    except IndexError:
                        sys.exit(f"agent policy: {args.source} does not exist")
                print(json.dumps(policy,indent=1))

    elif args.cmd == 'template':
        if args.action == 'init':
            template_recreate_from_ds(args.namespace)
        elif args.action == 'details':
            p = get_elastic(ELASTIC_HOST,f"_index_template/{args.source}")
            print(json.dumps(p,indent=1))
        elif args.action == 'list':
            resp=get_elastic(ELASTIC_HOST,f"_data_stream/*-{args.namespace}")
            for ds in resp['data_streams']:
               
               if re.search(args.namespace, ds['template']):
                   W = ""
               else:
                   WARN['N'] = "[!N] = not using a namespaced template"
                   W =  txt.BOLD + "[!N]" + txt.END

               if args.action == 'details':
                   print(f"{ds['name']}: {ds['template']} {W}")
                   print(f"  - ilm_policy: {ds['ilm_policy']}")
                   print("  - indices:")
                   for index in ds['indices']:
                       print(f"    {index['index_name']}: {index['ilm_policy']}")
               else:
                   print(f"{ds['name']}: {ds['template']} {W}")
        elif args.action == 'update':
            p = get_elastic(ELASTIC_HOST,f"_index_template/{args.source}")
            t = p['index_templates'][0]['index_template']
            if args.lifecycle_policy == 'none':
                try:
                    del t['template']['settings']
                except KeyError:
                    pass
            elif args.lifecycle_policy:
                dict_append(t)['template']['settings']['index']['lifecycle']['name'] = args.lifecycle_policy
            if args.retention_days == 0:
                dict_append(t)['template']['lifecycle']['enabled'] = False
            elif args.retention_days:
                dict_append(t)['template']['lifecycle']['enabled'] = True
                dict_append(t)['template']['lifecycle']['data_retention'] = f"{args.retention_days}d"

            res = post_elastic(ELASTIC_HOST,f"_index_template/{args.source}",t)
            print(json.dumps(res,indent=1))

    print_warns(WARN)

def print_warns(WARNS):
    for w in WARNS:
        print(txt.BOLD + "* " + txt.END + WARNS[w])
        
def agent_policy_rename(POLICY,NAMESPACE,NAME):
    for d in ('id','version','revision','updated_at','updated_by','agents',
              'unprivileged_agents','status','is_managed','is_protected','schema_version','inactivity_timeout'):
        del POLICY[d]
    
    POLICY['namespace'] = NAMESPACE
    POLICY['name'] = NAME

    new_packages = []
    for p in POLICY['package_policies']:
        new_name = re.sub("^[^-]+",NAMESPACE,p['name'])
        new_name = re.sub(" \(.*\)","",new_name)
        p['name'] = new_name
        for d in ('id','version','updated_at','updated_by','revision','created_at','created_by','policy_id','policy_ids'):
            del p[d]

        new_inputs = []
        for i in p['inputs']:
            new_streams = []
            for s in i['streams']:
                del s['id']
                new_streams.append(s)

            del i['streams']
            i['streams'] = new_streams

            new_inputs.append(i)

        del p['inputs']
        p['inputs'] = new_inputs

        new_packages.append(p)

    del POLICY['package_policies']
    #POLICY['package_policies'] = new_packages
    return POLICY,new_packages

def post_elastic(HOST, LOC, PAYLOAD):
    url = f'https://{HOST}/{LOC}'
    headers = {
        'kbn-xsrf': 'reporting',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {API_KEY}',
        'Elastic-Api-Version': '2023-10-31'
    }
    response = requests.post(url, headers=headers, json=PAYLOAD, verify=VERIFY) 
    if response.status_code == 200:
        content = response.json()
        return content
    else:
        response.raise_for_status()

def put_elastic(HOST, LOC, PAYLOAD):
    print(f"Creating {LOC}")
    
    url = f'https://{HOST}/{LOC}'
    headers = {
        'kbn-xsrf': 'reporting',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {API_KEY}'
    }
    response = requests.put(url, headers=headers, json=PAYLOAD, verify=VERIFY) 
    if response.status_code == 200:
        content = response.json() 
        return content
    else:
        response.raise_for_status() 

def get_elastic(HOST, LOC):
    url = f'https://{HOST}/{LOC}'
    headers = {
        'kbn-xsrf': 'reporting',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {API_KEY}'
    }
    response = requests.get(url, headers=headers, verify=VERIFY)
    if response.status_code == 200:
        content = response.json() 
        return content
    else:
        response.raise_for_status()

def template_recreate_from_ds(NAMESPACE):
    # get list of all data streams in namespace, and the current templates
    # then create new templates specific for that namespace
    action=(f"_data_stream/*-{NAMESPACE}")
    dstreams = get_elastic(ELASTIC_HOST,action)
    for ds in dstreams['data_streams']:
        if "-"+NAMESPACE in ds['template']:
            print(f"Namespaced template {ds['template']} already exists...")
            continue

        resp = get_elastic(ELASTIC_HOST,f"_index_template/{ds['template']}")

        template = resp['index_templates'][0]['index_template']
        template_name = resp['index_templates'][0]['name']
        index_pattern=template['index_patterns'][0]
        prio=template['priority']
        
        new_name = (f"{template_name}-{NAMESPACE}") 

        ## replace data in old template definition with new values 
        # we have to deal with generic/catchall templates differently
        # higher prio = pattern will be matched first before a matching pattern in a lower priority template
        if index_pattern == "metrics-*-*":
            new_pattern =  (f"metrics-*-{NAMESPACE}")
            new_prio = prio + 49
        elif index_pattern == "logs-*-*":
            new_pattern =  (f"logs-*-{NAMESPACE}")
            new_prio = prio + 49
        else:
            new_pattern =  index_pattern.replace("-*",f"-{NAMESPACE}*",1)
            new_prio = prio + 50
   
        # add lifecycle policy:  metrics-NAMESPACE or logs-NAMESPACE
        if "metrics" in index_pattern:
            try: 
                template['template']['settings'] = {'index': {'lifecycle': { 'name': 'metrics-'+NAMESPACE } } }
            except KeyError:
                template['template'] = {'settings': {'index': {'lifecycle': { 'name': 'metrics-'+NAMESPACE } } } }
        elif "logs" in index_pattern:
            try:
                template['template']['settings'] = {'index': {'lifecycle': { 'name': 'logs-'+NAMESPACE } } }
            except KeyError:
                template['template'] = {'settings': {'index': {'lifecycle': { 'name': 'logs-'+NAMESPACE } } } }
        else:
            print (f"{index_pattern} doesn't look like a template we can manage")

        # specify data retention in template if desired
        if args.retention_days:
            template['template']['lifecycle'] = { "enabled": "true", "data_retention": str(args.retention_days)+"d" }

        template['index_patterns'][0] = new_pattern
        template['priority'] = new_prio
        template['_meta']['managed_by'] = "prth"
        template['_meta']['managed'] = False
        resp = put_elastic(ELASTIC_HOST,f"_index_template/{new_name}",template)
        print(resp)

if __name__ == '__main__':
    main()
