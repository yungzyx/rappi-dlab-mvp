# shellcheck shell=bash
# Se carga con `.` (backup-nightly.sh y la prueba de restauración, en el contenedor jobs). pgpass_from_database_url
# deja la clave de DATABASE_URL en un archivo de claves temporal (0600) y exporta PGPASSFILE con su ruta: pg_dump y
# pg_restore la leen de ahí y nunca va en su argv, que `ps` muestra (también desde el servidor) mientras corren. Deja en
# PG_URL la misma URL sin la clave. Quien la llama borra "$PGPASSFILE" en su trap.
pgpass_from_database_url() {
  local rest=${DATABASE_URL#*://} userinfo secret=""
  PG_URL=$DATABASE_URL
  if [ "${rest%%@*}" != "$rest" ]; then  # hay usuario (y quizás clave) antes de la @
    userinfo=${rest%%@*}
    if [ "${userinfo#*:}" != "$userinfo" ]; then
      secret=${userinfo#*:}
      # shellcheck disable=SC2034  # PG_URL es para quien carga este archivo
      PG_URL="${DATABASE_URL%%://*}://${userinfo%%:*}@${rest#*@}"
    fi
  fi
  secret=$(printf '%b' "${secret//%/\\x}")  # la URL la trae con %xx
  secret=${secret//\\/\\\\}  # en el archivo de claves, «\» y «:» van escapados
  secret=${secret//:/\\:}
  PGPASSFILE=$(umask 077 && mktemp)
  printf '*:*:*:*:%s\n' "$secret" > "$PGPASSFILE"
  export PGPASSFILE
}
