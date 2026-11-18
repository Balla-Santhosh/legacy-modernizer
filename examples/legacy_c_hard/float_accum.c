/* float_accum.c - legacy sensor averaging that accumulates in single-precision float.
 * Trap: the arithmetic is float, not double; results printed with %.6f differ if "modernized" to double.
 */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    int n, i;
    float step, sum = 0.0f, mx = 0.0f;
    if (argc != 3) {
        fprintf(stderr, "usage: float_accum N STEP\n");
        return 2;
    }
    n = atoi(argv[1]);
    step = (float)atof(argv[2]);
    for (i = 0; i < n; i++) {
        float v = step * (float)(i % 7);
        sum += v;
        if (v > mx) mx = v;
    }
    printf("sum=%.6f\n", sum);
    printf("mean=%.6f\n", n ? sum / n : 0.0f);
    printf("max=%.6f trunc=%d\n", mx, (int)(sum / 3));
    printf("g=%g\n", sum);
    return 0;
}
