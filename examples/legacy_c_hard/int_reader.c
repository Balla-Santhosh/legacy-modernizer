/* int_reader.c - sums integers from stdin with scanf until input stops matching.
 * Trap: scanf stops at the first non-integer token and reports how far it got;
 * the program's exit code encodes why it stopped.
 */
#include <stdio.h>

int main(void)
{
    int v, n = 0, rc;
    long sum = 0;
    int mn = 0, mx = 0;
    while ((rc = scanf("%d", &v)) == 1) {
        if (n == 0 || v < mn) mn = v;
        if (n == 0 || v > mx) mx = v;
        sum += v;
        n++;
    }
    printf("read %d ints, sum %ld", n, sum);
    if (n) printf(", min %d, max %d, mean %.2f", mn, mx, (double)sum / n);
    printf("\n");
    if (rc == EOF) return 0;
    {
        char rest[32];
        if (scanf("%31s", rest) == 1) printf("stopped at \"%s\"\n", rest);
    }
    return 5;
}
