/* rpn.c - reverse-polish calculator over a hand-rolled linked-list stack.
 * Reads one expression per line from stdin, prints the result or "error".
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct node {
    double v;
    struct node *next;
};

static struct node *top = NULL;
static int depth = 0;

static void push(double v)
{
    struct node *n = (struct node *)malloc(sizeof(struct node));
    n->v = v;
    n->next = top;
    top = n;
    depth++;
}

static int pop(double *out)
{
    struct node *n;
    if (top == NULL) return 0;
    n = top;
    *out = n->v;
    top = n->next;
    free(n);
    depth--;
    return 1;
}

static void clear(void)
{
    double d;
    while (pop(&d)) ;
}

int main(void)
{
    char line[512];
    while (fgets(line, sizeof line, stdin)) {
        char *tok = strtok(line, " \t\r\n");
        int ok = 1;
        double a, b, r;
        if (tok == NULL) continue;
        while (tok && ok) {
            if (strlen(tok) == 1 && strchr("+-*/", tok[0])) {
                if (!pop(&b) || !pop(&a)) { ok = 0; break; }
                switch (tok[0]) {
                case '+': r = a + b; break;
                case '-': r = a - b; break;
                case '*': r = a * b; break;
                default:
                    if (b == 0) { ok = 0; r = 0; }
                    else r = a / b;
                }
                push(r);
            } else {
                char *end;
                double v = strtod(tok, &end);
                if (*end != '\0') { ok = 0; break; }
                push(v);
            }
            tok = strtok(NULL, " \t\r\n");
        }
        if (ok && depth == 1 && pop(&r)) printf("%.6g\n", r);
        else printf("error\n");
        clear();
    }
    return 0;
}
