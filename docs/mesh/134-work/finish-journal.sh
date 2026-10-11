set -u
say() { printf '\n=== %s ===\n' "$1"; }

say "journal (step 1): a checkout of harness-config on the authority"
# The canonical checkout is /root/code/harness-config. It is seeded from the local machine's `main`
# (already on this box at /root/hc-main.bundle) and pushed to a bare repo on the VPS, which is a
# real, off-authority, network-reachable remote. Not the office box: it is the frozen anchor and it
# is being retired, and a journal commit that backs up onto the machine being retired is not a
# backup. Not GitHub: the cloud box has no write credential for it (see the report).
if [ -d /root/code/harness-config/.git ]; then
  echo "already a git checkout: $(git -C /root/code/harness-config rev-parse --short HEAD)"
else
  rm -rf /root/code/harness-config
  git clone -q /root/hc-main.bundle /root/code/harness-config
  git -C /root/code/harness-config checkout -q main 2>/dev/null || git -C /root/code/harness-config checkout -q master
fi
git -C /root/code/harness-config log --oneline -1
echo "--- journal tree present? ---"
ls -d /root/code/harness-config/journal /root/code/harness-config/journal/tools /root/code/harness-config/journal/entries
git -C /root/code/harness-config config user.name  "zabz"
git -C /root/code/harness-config config user.email "zabz@lakewoodphoneandtech.com"
git -C /root/code/harness-config config --add safe.directory /root/code/harness-config

say "journal (step 2): the remote it pushes to, on the VPS"
VPS=2.28.33.58
VPSKEY=/root/.ssh/id_ed25519_hetzner
ssh -i "$VPSKEY" -o BatchMode=yes -o ConnectTimeout=15 root@$VPS \
  'mkdir -p /srv/git && if [ ! -d /srv/git/harness-config.git ]; then git init -q --bare /srv/git/harness-config.git; fi; git -C /srv/git/harness-config.git rev-parse --is-bare-repository; df -h / | tail -1'
git -C /root/code/harness-config remote remove origin 2>/dev/null || true
git -C /root/code/harness-config remote add origin root@$VPS:/srv/git/harness-config.git
git -C /root/code/harness-config config core.sshCommand "ssh -i $VPSKEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
echo "--- first push (proves the journal leaves the authority) ---"
sudo -u root git -C /root/code/harness-config push -u origin main 2>&1 | tail -5

say "the remote's own copy, read back over ssh"
ssh -i "$VPSKEY" -o BatchMode=yes root@$VPS 'git -C /srv/git/harness-config.git log --oneline -1; git -C /srv/git/harness-config.git count-objects -vH | head -3'

say "journal-commit itself, run deliberately (this is the ledger entry that matters)"
/usr/local/bin/cron-wrap.sh journal-commit; echo "rc=$?"
/usr/local/bin/journal-commit.sh; echo "journal-commit.sh rc=$?"
ls -la /root/.harness-config-autosync/ 2>/dev/null
tail -5 /root/.harness-config-autosync/journal-commit.log 2>/dev/null
echo "--- and the remote advanced? ---"
ssh -i "$VPSKEY" -o BatchMode=yes root@$VPS 'git -C /srv/git/harness-config.git log --oneline -3'
rm -f /root/hc-main.bundle
df -h / | tail -1
