/* macro_eval.c - legacy stats with function-like macros.
 * Trap: macros evaluate arguments twice and lack parentheses; behaviour must be preserved
 * exactly (e.g. SQUARE(x + 1) is x + 1*x + 1, and MAX(i++, j) increments i twice when i > j).
 */
#include <stdio.h>
#include <stdlib.h>

#define SQUARE(x) x * x
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define HALF(x) x / 2

int main(int argc, char **argv)
{
    int i, j, k, m;
    if (argc != 3) {
        printf("usage: macro_eval I J\n");
        return 1;
    }
    i = atoi(argv[1]);
    j = atoi(argv[2]);
    printf("square(i+1)=%d\n", SQUARE(i + 1));
    printf("half(i+j)=%d\n", HALF(i + j));
    k = i;
    m = MAX(k++, j);
    printf("max=%d k=%d\n", m, k);
    printf("100/square(j)=%d\n", j ? 100 / SQUARE(j) : -1);
    return 0;
}
