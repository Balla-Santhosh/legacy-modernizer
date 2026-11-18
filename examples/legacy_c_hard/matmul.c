/* matmul.c - multiplies two pseudo-random N x N integer matrices and prints a checksum.
 * Compute-heavy: used to measure speedup. Uses a fixed LCG so output is deterministic.
 */
#include <stdio.h>
#include <stdlib.h>

static unsigned int seed = 12345u;

static int rnd(void)
{
    seed = seed * 1103515245u + 12345u;
    return (int)((seed >> 16) & 0x7fff) % 100;
}

int main(int argc, char **argv)
{
    int n, i, j, k;
    int *a, *b;
    long long *c, checksum = 0, trace = 0;
    if (argc != 2 || (n = atoi(argv[1])) <= 0 || n > 2000) {
        printf("usage: matmul N (1..2000)\n");
        return 1;
    }
    a = (int *)malloc(sizeof(int) * n * n);
    b = (int *)malloc(sizeof(int) * n * n);
    c = (long long *)calloc((size_t)n * n, sizeof(long long));
    for (i = 0; i < n * n; i++) a[i] = rnd();
    for (i = 0; i < n * n; i++) b[i] = rnd();
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            for (k = 0; k < n; k++)
                c[i * n + j] += (long long)a[i * n + k] * b[k * n + j];
    for (i = 0; i < n * n; i++) checksum = (checksum * 31 + c[i]) % 1000000007LL;
    for (i = 0; i < n; i++) trace += c[i * n + i];
    printf("n=%d checksum=%lld trace=%lld corner=%lld\n", n, checksum, trace, c[n * n - 1]);
    free(a); free(b); free(c);
    return 0;
}
