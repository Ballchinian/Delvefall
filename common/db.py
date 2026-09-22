#what every ingest connection is opened with.
#
#on 09-22 ingest.tags sat in COPY for 14 minutes with nothing coming back down
#the socket, holding a transaction web's own boot queued behind, and the job's 6
#hour ceiling was the only thing that would ever have ended it.
#
#probes start after 30s of silence, and the user timeout is what ends the
#connection, because linux lets TCP_USER_TIMEOUT override keepalives_count once
#it is set: a black holed link dies about two and a half minutes in. windows has
#no such option and stops at the count instead, so about a minute there.
#
#two minutes rather than less because the same timeout covers data the kernel
#could not send into a receive window the server has shut, which is a busy
#postgres rather than a dead one.
#
#web is not here: it deploys the web folder alone, and its pool checks a
#connection on every checkout
KEEPALIVE = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "tcp_user_timeout": 120000,
}
