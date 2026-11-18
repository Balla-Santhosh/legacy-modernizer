/* ringbuf.c - fixed-capacity circular queue driven by commands on stdin.
 * Commands: push N | pop | peek | size | dump. Capacity 4; push on full overwrites the oldest.
 * Trap: overwrite-on-full semantics and index wraparound must be preserved.
 */
#include <stdio.h>
#include <string.h>

#define CAP 4

static int buf[CAP];
static int head = 0, count = 0, dropped = 0;

static void push(int v)
{
    int tail = (head + count) % CAP;
    buf[tail] = v;
    if (count == CAP) { head = (head + 1) % CAP; dropped++; }
    else count++;
}

int main(void)
{
    char cmd[16];
    int v, errors = 0, i;
    while (scanf("%15s", cmd) == 1) {
        if (strcmp(cmd, "push") == 0) {
            if (scanf("%d", &v) != 1) { printf("push needs a number\n"); return 7; }
            push(v);
        } else if (strcmp(cmd, "pop") == 0 || strcmp(cmd, "peek") == 0) {
            if (count == 0) { printf("empty\n"); errors++; continue; }
            printf("%s %d\n", cmd, buf[head]);
            if (cmd[1] == 'o') { head = (head + 1) % CAP; count--; }
        } else if (strcmp(cmd, "size") == 0) {
            printf("size %d dropped %d\n", count, dropped);
        } else if (strcmp(cmd, "dump") == 0) {
            printf("[");
            for (i = 0; i < count; i++) printf(i ? ",%d" : "%d", buf[(head + i) % CAP]);
            printf("]\n");
        } else {
            printf("unknown '%s'\n", cmd);
            errors++;
        }
    }
    return errors > 2 ? 6 : 0;
}
