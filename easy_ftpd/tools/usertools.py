def is_hash(pw):
    if len(pw) == 40:
        return True
    else:
        return False

class User(object):
    def __init__(self, name, pw, perms, root):
        self.name = name
        self.pw = pw
        self.perms = perms
        self.root = root

    def change_pass(self, pw, plaintext=False):
        if plaintext:
            self.pw = pw
        else:
            self.pw = User.get_hash(self.name, pw)

    def __str__(self):
        return self.name + ":" + self.pwhash + ":" + self.perms + \
               ":" + self.root

    #@staticmethod #not used due to pesky 2.3
    def get_hash(name, pw):
        import sha
        return sha.new(name+pw).hexdigest()

    get_hash = staticmethod(get_hash)

def load(userfile):
    users = {}
    
    for line in userfile:
        if line.startswith("#"): # comment. ignore
            continue
        name,pw,perms,root = line.split(":",3)
        root = root.rstrip("\n")

        users[name] = User(name, pw, perms, root)

    userfile.close()
    return users

def dump(users, userfile):
    if "anonymous" in users: # anonymous goes first
        user = users["anonymous"]
        print >> userfile, user
        print >> userfile, ""
    for user in users:
        if user == "anonymous": # already handled!
            continue
        print >> userfile, users[user]
    userfile.close()

def create_user((name, pw, perms, root), userdict):
    if name in userdict:
        raise NameError("User with that name already exist")

    user = User(name, pw, perms, root)
    userdict[user] = user

    print "User",user,"added!"

def del_user(name, userdict):
    if name not in userdict:
        raise NameError("User with that name doesn't exist")

    userdict.pop(name)

    print "User",user,"deleted!"

def modify_user(name, newpw=None, newperms=None, newroot=None):
    if name not in userdict:
        raise NameError("User with that name doesn't exist")

    user = users[name]

    if newpw:
        user.change_pass(newpw)

    if newperms:
        user.perms = newperms

    if newroot:
        user.root = newroot

    print "User",user,"modified!"

def main():
    f = load(open("users"))
    import sys
    dump(f,sys.stdout)

if __name__ == "__main__":
    main()
