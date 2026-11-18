/* csv_fields.c - prints the fields of each comma-separated line using strtok.
 * Trap: strtok collapses consecutive delimiters and skips leading/trailing ones,
 * so "a,,b" has 2 fields, not 3. A "correct" CSV splitter changes behaviour.
 */
#include <stdio.h>
#include <string.h>

int main(void)
{
    char line[256];
    int lineno = 0;
    while (fgets(line, sizeof line, stdin)) {
        char *tok;
        int nf = 0;
        lineno++;
        line[strcspn(line, "\r\n")] = '\0';
        printf("line %d:", lineno);
        for (tok = strtok(line, ","); tok; tok = strtok(NULL, ",")) {
            printf(" [%s]", tok);
            nf++;
        }
        printf(" (%d fields)\n", nf);
    }
    return lineno == 0 ? 3 : 0;
}
