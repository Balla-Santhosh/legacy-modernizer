/* config_load.c - reads key=value config from stdin with goto-based error handling.
 * Trap: distinct exit codes per error, messages split between stdout and stderr,
 * and partial output already printed before an error must still appear.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

#define MAXKEYS 8

int main(void)
{
    char line[128];
    char *keys[MAXKEYS];
    int nkeys = 0, lineno = 0, rc = 0, i;

    while (fgets(line, sizeof line, stdin)) {
        char *eq, *k, *v;
        lineno++;
        line[strcspn(line, "\n")] = 0;
        if (line[0] == '#' || line[0] == 0) continue;
        eq = strchr(line, '=');
        if (!eq) { rc = 10; goto bad_syntax; }
        *eq = 0;
        k = line;
        v = eq + 1;
        if (!isalpha((unsigned char)k[0])) { rc = 11; goto bad_key; }
        for (i = 0; i < nkeys; i++)
            if (strcmp(keys[i], k) == 0) { rc = 12; goto dup_key; }
        if (nkeys == MAXKEYS) { rc = 13; goto too_many; }
        keys[nkeys] = malloc(strlen(k) + 1);
        strcpy(keys[nkeys++], k);
        printf("%s = \"%s\"\n", k, v);
    }
    printf("loaded %d keys\n", nkeys);
    goto cleanup;

bad_syntax:
    fprintf(stderr, "line %d: missing '='\n", lineno);
    goto cleanup;
bad_key:
    fprintf(stderr, "line %d: bad key\n", lineno);
    goto cleanup;
dup_key:
    fprintf(stderr, "line %d: duplicate key\n", lineno);
    printf("partial: %d keys before error\n", nkeys);
    goto cleanup;
too_many:
    fprintf(stderr, "too many keys\n");
cleanup:
    for (i = 0; i < nkeys; i++) free(keys[i]);
    return rc;
}
