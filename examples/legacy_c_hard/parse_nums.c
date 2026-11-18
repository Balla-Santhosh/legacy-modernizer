/* parse_nums.c - legacy argument parser built on atoi/atol/atof.
 * Trap: atoi("12abc") == 12, atoi("abc") == 0, never throws; std::stoi would throw or differ.
 */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    int i;
    long total = 0;
    if (argc < 2) {
        printf("nothing to parse\n");
        return 0;
    }
    for (i = 1; i < argc; i++) {
        int v = atoi(argv[i]);
        double d = atof(argv[i]);
        printf("%-8s -> int %d, double %.3f, div7 %d, mod7 %d\n", argv[i], v, d, v / 7, v % 7);
        total += v;
    }
    printf("total %ld\n", total);
    return total < 0 ? 1 : 0;
}
