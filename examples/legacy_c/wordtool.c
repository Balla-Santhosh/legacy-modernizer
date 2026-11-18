/* wordtool.c - legacy string utility (1998 style).
 * usage: wordtool <mode> <words...>   mode = rev | upper | join
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAXBUF 1024

static char *dupstr(const char *s)
{
    char *b = malloc(strlen(s) + 1);
    strcpy(b, s);               /* no bounds check */
    return b;
}

static void reverse(char *s)
{
    int i, j;
    char t;
    for (i = 0, j = strlen(s) - 1; i < j; i++, j--) {
        t = s[i]; s[i] = s[j]; s[j] = t;
    }
}

static void upper(char *s)
{
    while (*s) { *s = toupper(*s); s++; }
}

int main(int argc, char **argv)
{
    char buf[MAXBUF];
    int i;
    if (argc < 3) {
        fprintf(stderr, "usage: %s rev|upper|join words...\n", argv[0]);
        return 2;
    }
    if (strcmp(argv[1], "join") == 0) {
        buf[0] = '\0';
        for (i = 2; i < argc; i++) {
            strcat(buf, argv[i]);
            if (i + 1 < argc) strcat(buf, "-");
        }
        printf("%s\n", buf);
        return 0;
    }
    for (i = 2; i < argc; i++) {
        char *w = dupstr(argv[i]);
        if (strcmp(argv[1], "rev") == 0) reverse(w);
        else if (strcmp(argv[1], "upper") == 0) upper(w);
        else { free(w); fprintf(stderr, "bad mode\n"); return 1; }
        printf("%s%s", w, i + 1 < argc ? " " : "\n");
        free(w);
    }
    return 0;
}
