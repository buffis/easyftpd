def load(configfile):
    config = {}

    for line in configfile:
        if not line or line.startswith("#"):
            continue # empty line or comment
                                   
        key,value = line.split(":",1)
        config[key] = value.lstrip(" ").rstrip("\n").replace("\\n","\n")
    
    return config

def dump(configs, configfile):
    for key in configs:
        print >> configfile, key+":"+configs[key]
    configfile.close()
