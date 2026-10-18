# Security

By default Papelada has no login: anyone who can reach it can see and change every
document. Run it on your home network, or turn on the built-in login.

To turn it on, set `USERNAME` and `PASSWORD` (or `PASSWORD_FILE`) and restart. Both
or neither: with only one of them, Papelada refuses to start. Then:

- Opening the app asks for the username and password, and every API route (including
  `/api/docs`) rejects requests without a session. Only `/api/health`, which Docker's
  health check uses, and the login itself are open.
- A session is a cookie that lasts 14 days, and there is a sign-out button in the
  header. Restarting Papelada signs everyone out.
- After 5 wrong passwords from one address in 15 minutes, that address is locked out
  for the rest of the window (and everyone is, after 50 in total). Behind a reverse
  proxy, every request comes from the proxy's address, so wrong guesses lock out
  everyone, you included, until the window passes.
- There is one user, with no registration and no password reset. To change the
  credentials, change the variables and restart. The password is never written to the
  volume and has nothing to do with `ENCRYPTION_KEY`.

The login stops other people on your network, but it's only as private as the
connection: over plain `http://` the password and the documents travel in the clear.
Outside your home network, serve Papelada over HTTPS (a reverse proxy, or a VPN such
as Tailscale or WireGuard), and consider adding a second layer such as Cloudflare
Access. The frontend only uses relative URLs, so it also works under a path prefix
(e.g. `https://example.com/papelada/`, trailing slash included) behind a reverse proxy
that strips that prefix.
