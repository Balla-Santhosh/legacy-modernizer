/* report_table.c - formats a score report from "name score count" lines on stdin.
 * Trap: exact printf formatting (%-10s, %8.3f, %e, %g, %+d, %x, %o, %%).
 */
#include <stdio.h>
#include <string.h>

int main(void)
{
    char name[64];
    double score, total = 0.0;
    int count, n = 0, sumc = 0;
    printf("%-10s|%8s|%6s|%12s\n", "NAME", "SCORE", "COUNT", "SCI");
    while (scanf("%63s %lf %d", name, &score, &count) == 3) {
        printf("%-10.10s|%8.3f|%+6d|%12.4e\n", name, score, count, score);
        total += score;
        sumc += count;
        n++;
    }
    if (n == 0) {
        printf("no rows\n");
        return 1;
    }
    printf("rows=%d avg=%g total=%.2f%% hex=%#x oct=%o\n", n, total / n, total, sumc, sumc);
    return 0;
}
