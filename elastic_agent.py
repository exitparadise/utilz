#!/usr/bin/env python

import argparse, requests, json, os, sys, re

parser = argparse.ArgumentParser(description="Elastic Agent Management Utility")
requests.packages.urllib3.disable_warnings() 

subparsers = parser.add_subparsers(dest="cmd")
parser_template = subparsers.add_parser("template", help="index template actions")
parser_template.add_argument("action", choices=["list","json","init","details","update"])
parser_template.add_argument("object", nargs="?", help="the namespace or index template")
parser_template.add_argument("-l", "--lifecycle-policy", help="when action is 'update', add this policy. 'none' means remove policy")
parser_template.add_argument("-d", "--retention-days", type=int, help="when action is 'init' or 'update', number of retention days to apply")

parser_agent = subparsers.add_parser("agent", help="agent policy actions")
parser_agent.add_argument("action", choices=["list","details","json","copy"])
parser_agent.add_argument("object", nargs="?", help="the namespace or agent policy")
parser_agent.add_argument("source", nargs="?", help="when action is 'copy', the namespace or agent policy to copy")
parser_agent.add_argument("-f", "--full", action="store_true", help="when action is 'json', enable full output")

parser_ds = subparsers.add_parser("ds", help="datastream actions")
parser_ds.add_argument("action", choices=["list","details","applyilm"])
parser_ds.add_argument("object", nargs="?", help="the datastream or namespace we would like to target, used with 'list', 'details' and 'applyilm'")
parser_ds.add_argument("-l", "--show-lifecycle", action="store_true")

parser_ilm = subparsers.add_parser("ilm", help="ILM Policy actions")
parser_ilm.add_argument("action", choices=["list","details","json"])
parser_ilm.add_argument("object", nargs="?", help="the ilm policy we would like to target, used with 'details' and 'json'")

try:
    args = parser.parse_args()
except:
    parser.print_help()
    sys.exit(0)

NAMESPACES = ('default','prod','dev','qa')
API_KEY=os.getenv('ELASTIC_API_KEY')
ELASTIC_HOST="elastic-api:9200"
KIBANA_HOST="kibana-api:5601"
VERIFY=False
WARN={}

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
    if args.cmd == 'ilm':
        if args.action == 'list':
            ilms = get_elastic(ELASTIC_HOST,f"_ilm/policy")
            for ilm in ilms:
                print(ilm)
        elif args.action in ('details', 'json'):
            try:
                ilms = get_elastic(ELASTIC_HOST,f"_ilm/policy/{args.object}")
            except:
                sys.exit(f"could not find ilm policy: {args.object}")

            if args.action == 'json':
                for ilm in ilms:
                    print(json.dumps(ilms[ilm],indent=1))
            else:
                for ilm in ilms:
                    print(f"ilm_policy: {ilm}")
                    print("  phases:")
                    for p in ilms[ilm]['policy']['phases']:
                        ilm_phase_show(p,ilms[ilm]['policy']['phases'][p])
                    print("  used_by:")
                    for i in ilms[ilm]['in_use_by']['indices']:
                        print(f"  - index: {i}")
                    for d in ilms[ilm]['in_use_by']['data_streams']:
                        print(f"  - datastream: {d}")
                    for c in ilms[ilm]['in_use_by']['composable_templates']:
                        print(f"  - index_template: {c}")
                        
    elif args.cmd == 'agent':
        if args.action in ('list', 'details'):
            if not args.object in NAMESPACES:
                sys.exit("agent actions require <object>, a valid namespace name")
            else:
                pol = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.namespace:{args.object}")
                for policy in pol['items']:
                    if policy['namespace'] == args.object:
                        print(txt.BOLD + f"{policy['name']}" + txt.END + f" agents: {policy['agents']}")
                        if args.action == 'details':
                            full = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{policy['id']}/full")
                            print("    integrations:")
                            for input in full['item']['inputs']:
                                print(f"    - {input['name']} - {input['type']}")
        elif args.action == 'copy':
            if not args.source:
                sys.exit("copy action requires <source>, an agent policy name") 
            else:
                p = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.name:{args.source}")
                policy = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{p['items'][0]['id']}")
                new_name = re.sub("^[^-]+",args.object,args.source)

                print(f"copy {policy['item']['name']}/{policy['item']['id']} to {new_name}")

                (new_policy,packages) = agent_policy_rename(policy['item'], args.object, new_name)
                new_policy_def = post_elastic(KIBANA_HOST,f"api/fleet/agent_policies",new_policy)
                print(f" - new policy ID: {new_policy_def['item']['id']}")
                
                for pkg in packages:
                   pkg['policy_id'] = new_policy_def['item']['id']
                   # mysql integration password can't be copied, so we remove it and prompt user to re-add through UI
                   W = raise_warn(pkg['package']['name'],'mysql','equals','P')
                   if pkg['package']['name'] == 'mysql':
                       del pkg['secret_references']
                       for input in pkg['inputs']:
                           if input['type'] == 'mysql/metrics':
                               input['vars']['password']['value'] = ""
                               for stream in input['streams']:
                                   try:
                                       del stream['compiled_stream'] 
                                   except:
                                       pass

                   pkgadd = post_elastic(KIBANA_HOST,f"api/fleet/package_policies",pkg)
                   print(f" - add integration: {pkgadd['item']['name']}/{pkgadd['item']['id']} {W}")
                print("Done!")

        elif args.action == 'json':
            if not args.object:
                sys.exit("json action requires <object>, an agent policy name") 
            else:
                p = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies?kuery=ingest-agent-policies.name:{args.object}")
                if args.full:
                    FULL = '/full'
                else: 
                    FULL = ''
                try:
                    policy = get_elastic(KIBANA_HOST,f"api/fleet/agent_policies/{p['items'][0]['id']}{FULL}")
                except IndexError:
                    sys.exit(f"agent policy: {args.object} does not exist")
                print(json.dumps(policy,indent=1))

    elif args.cmd == 'ds':
        if args.action in ('list', 'details'):
            if args.object in NAMESPACES:
                resp=get_elastic(ELASTIC_HOST,f"_data_stream/*-{args.object}")
            elif args.object and args.object != 'all':
                try:
                    resp=get_elastic(ELASTIC_HOST,f"_data_stream/{args.object}")
                except:
                    sys.exit(f"could not find datastream: {args.object}")
            else:
                sys.exit("datastream actions require <object>, a valid namespace or a datastream name")

            for ds in resp['data_streams']:
               
               W = raise_warn(args.object,ds['template'],'search','N')

               if args.action == 'details':
                   print(f"{ds['name']}:")
                   print(f"  - index_template: {ds['template']} {W}")
                   print(f"  - ilm_policy: {ds['ilm_policy']}")
                   print("  - indices:")

                   if args.show_lifecycle:
                       il = get_elastic(ELASTIC_HOST,f"{ds['name']}/_ilm/explain")
                       for id in il['indices']:
                           try:
                               W2 = raise_warn(ds['ilm_policy'],il['indices'][id]['policy'],'equals','M')
                               age = il['indices'][id]['age']
                               phase = il['indices'][id]['phase']
                               ilname = il['indices'][id]['policy']
                           except:
                               W2 = raise_warn(ds['ilm_policy'],'None','equals','M')
                               age = 'N/A'
                               phase = 'N/A'
                               ilname = 'N/A'

                           print(f"    {id} ilm:{ilname} age:{age} phase:{phase} {W2}")
                   else:
                       for index in ds['indices']:
                           W2 = raise_warn(ds['ilm_policy'],index['ilm_policy'],'equals','M')
                           print(f"    {index['index_name']} ilm:{index['ilm_policy']} {W2}")

               else:
                   print(f"{ds['name']}: {ds['template']} {W}")
        elif args.action == 'applyilm':
            if args.object:
                resp=get_elastic(ELASTIC_HOST,f"_data_stream/{args.object}")
            else:
                sys.exit("applyilm action requires <object>, a datastream name")

            for ds in resp['data_streams']:
               print(f"applying {ds['ilm_policy']} to all indexes in {ds['name']}")
               for index in ds['indices']:
                   if ds['ilm_policy'] == index['ilm_policy']:
                       print(f"{index['index_name']} already has policy {ds['ilm_policy']}, skipping")
                   else:
                       print(f"update {index['index_name']} from {index['ilm_policy']} to {ds['ilm_policy']}")
                       payload = { "index.lifecycle.name": ds['ilm_policy'], "index.lifecycle.prefer_ilm": True }
                       resp = put_elastic(ELASTIC_HOST,f"{index['index_name']}/_settings",payload)
                       print(resp)
          
    elif args.cmd == 'template':
        if args.action == 'init' and args.object in NAMESPACES:
            template_recreate_from_ds(args.object)
        elif args.action == 'json':
            if args.object:
                try:
                    p = get_elastic(ELASTIC_HOST,f"_index_template/{args.object}")
                    print(json.dumps(p,indent=1))
                except:
                    sys.exit(f"template not found: {args.object}")
            else:
                sys.exit(f"json action requires <object>, an index template name")
        elif args.action in ('list', 'details'):
            if not args.object in NAMESPACES:
                sys.exit("template actions require <object>, a valid namespace or index template name")
            else:
                resp=get_elastic(ELASTIC_HOST,f"_index_template/*-{args.object}")
                for template in resp['index_templates']:
                
                   if re.search(args.object, template['name']):
                       W = ""
                   else:
                       WARN['N'] = "[!N] = not using a namespaced template"
                       W =  txt.BOLD + "[!N]" + txt.END

                   if args.action == 'details':
                       print(f"{template['name']}: {W}")
                       try:
                           print(f"  - ilm_policy: {template['index_template']['template']['settings']['index']['lifecycle']['name']}")
                       except KeyError:
                           print(f"  - ilm_policy: None")
                       try:
                           print(f"  - lifecycle data retention: {template['index_template']['template']['lifecycle']['data_retention']}")
                       except KeyError:
                           print(f"  - lifecycle data retention: None")
                       print("  - components:")
                       for comp in template['index_template']['composed_of']:
                           print(f"    {comp}")
                   else:
                       print(f"{template['name']} {W}")
        elif args.action == 'update':
            p = get_elastic(ELASTIC_HOST,f"_index_template/{args.object}")
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

            res = post_elastic(ELASTIC_HOST,f"_index_template/{args.object}",t)
            print(json.dumps(res,indent=1))
    else:
        parser.print_help()
        sys.exit(0)
    print_warns(WARN)

def ilm_phase_show(P,PHASE):
    print(f"  - {P}:")
    print(f"    min_age: {PHASE['min_age']}")
    print(f"    actions:")
    for a in PHASE['actions']:
            print(f"      - {a}")

def raise_warn(a,b,action,type):
    _warns = { 
               'N': "[!N] = not using a namespaced template",
               'M': "[!M] = ilm mismatch: index has different policy from datastream",
               'P': "[!P] = unable to copy passwords, edit integration through the UI to re-add"
             }

    if action == 'equals' and a == b:
        return ""
    elif action == 'search' and re.search(a, b):
        return ""
    else:
        WARN[type] = _warns[type]
        return txt.BOLD + f"[!{type}]" + txt.END

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
    url = f'https://{HOST}/{LOC}'
    headers = {
        'kbn-xsrf': 'reporting',
        'Content-Type': 'application/json',
        'Authorization': f'ApiKey {API_KEY}',
        'Elastic-Api-Version': '2023-10-31'
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
        
        new_name = (f"{template_name}-{NAMESPACE}") 

        ## replace data in old template definition with new values 
        # we have to deal with generic/catchall templates differently
        # higher prio = pattern will be matched first before a matching pattern in a lower priority template
        if index_pattern == "metrics-*-*":
            new_pattern =  (f"metrics-*-{NAMESPACE}")
            new_prio = template['priority'] + 49
        elif index_pattern == "logs-*-*":
            new_pattern =  (f"logs-*-{NAMESPACE}")
            new_prio = template['priority'] + 49
        else:
            new_pattern =  index_pattern.replace("-*",f"-{NAMESPACE}*",1)
            new_prio = template['priority'] + 50
   
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
