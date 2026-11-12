# MetaList vaults, backups, exports, and updates

Vaults isolate notes, preferences, tags, reminders, and authentication. A
vault is not a search context. Search contexts are saved searches within the same vault.
Open/Switch Vault… opens a picker of reachable vaults with two buttons: Open in
This Tab (switching keeps one tab) and Open in New Tab; with no other vault
yet it opens Create Vault… instead. Create Vault… opens
the new vault wizard: name and ports, then, in the new vault, a password, an AI
and bringing in notes. Rename Current Vault… opens a rename form. Delete Vault…
opens a confirmation form; do not execute deletion or imply it has happened.
Manage Vault Ports… edits saved future launch profiles; saving does not launch,
switch to, or restart a vault. Port changes take effect on a later launch.

Back Up Now… is an operation, not merely opening a dialog. It can prompt for
backup folder/settings and creates one versioned .tar.gz archive per vault
containing its notes database and its files (the file catalog and every stored file) when present. The result
shows one row per vault. The help action cannot invoke backup creation.
Backup reminder (menu: Off, Daily, Weekly, Every 2 weeks, Monthly; Weekly by
default) floats a card when this vault's newest backup is older than that;
its Back Up Now opens Backup Settings and × hides it for a day.
Restore from Backup… opens a picker for configured-folder snapshots. The user
chooses and confirms a restore; success is confirmed with OK before reloading.
Opening this picker neither restores data nor changes backups. Existing backup
files are immutable recovery artifacts: no rewriting/repackaging/migration of
historical backups, including after password or schema changes. Restore installs
and migrates the live database only, leaving its source unchanged. Keep the
password that was used for an older encrypted snapshot. The restored live copy
inherits that snapshot's password/encryption state; restore does not substitute
the current live password or choose a new password. A later explicit password
change affects only that restored live copy. A backup is not the same
as an HTML export.

Export View as HTML… exports the current view for viewing/sharing, not a full restorable
database backup. It and Print (note menu, view menu, palette `Print View…`) show
the view as it is shown (search, sort, Untagged; notes a search leaves out are
absent), after a dialog setting the title (it heads the file and names it;
Suggest with AI can propose one). An exported file starts collapsed and expanded
as MetaList shows the notes (embeds too), its arrows working; a print is light,
fully expanded, without arrows, keeping MetaList's colours.
When @password or @username notes would show, an Include Unredacted Passwords
(Usernames, or Usernames and Passwords) checkbox appears (unchecked: shown as
••••••••; checked: readable, and the file or print is not encrypted).
Exported files copy usernames, included passwords and copyable values on click.
Attach File… stores an attachment in the vault's files folder, one file per attachment. A file can be any size, as long as it fits on the disk with some room to spare. Over 100 MiB a file can't be previewed, read for search or inlined in an export; it is still kept, downloaded and found by its name.
Trim Unused Files… removes unused attachments and is not an opening action.
The agent can explain these operations but cannot execute them through help.

Version info shows application/database/runtime/vault and encryption status.
It also provides update information; managed uv installs can use the in-app
installer. Opening Version info does not install an update. The user controls
installation/restart; do not claim a particular installed/latest version unless
it was supplied. Local help references cannot establish current release data.
Updates validate a candidate before stopping live vaults and create fresh
backups of each vault's notes and attached files; old backup archives remain
unchanged. Restore refuses a backup with no attached files over a vault that
has some (backups made before an update by MetaList 0.27.0 and earlier have
none): choose another backup. Each vault keeps its newest 3
safety backups (made before an update or a database upgrade, in the vault's own
backups folder), and older ones are removed automatically once the update or
upgrade has succeeded; backups in a folder the user chose follow that folder's
own setting. Do not advise editing or deleting recovery archives to work around
a startup failure.
