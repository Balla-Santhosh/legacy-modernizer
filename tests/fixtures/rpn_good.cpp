#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::optional<double> evaluate(const std::string& line, bool& blank) {
    std::istringstream in(line);
    std::vector<double> stack;
    std::string tok;
    blank = true;
    while (in >> tok) {
        blank = false;
        if (tok.size() == 1 && std::string("+-*/").find(tok[0]) != std::string::npos) {
            if (stack.size() < 2) return std::nullopt;
            const double b = stack.back(); stack.pop_back();
            const double a = stack.back(); stack.pop_back();
            switch (tok[0]) {
                case '+': stack.push_back(a + b); break;
                case '-': stack.push_back(a - b); break;
                case '*': stack.push_back(a * b); break;
                default:
                    if (b == 0) return std::nullopt;
                    stack.push_back(a / b);
            }
        } else {
            char* end = nullptr;
            const double v = std::strtod(tok.c_str(), &end);
            if (*end != '\0') return std::nullopt;
            stack.push_back(v);
        }
    }
    if (stack.size() != 1) return std::nullopt;
    return stack.back();
}

}  // namespace

int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        bool blank = true;
        const auto r = evaluate(line, blank);
        if (blank) continue;
        if (r) std::printf("%.6g\n", *r);
        else std::printf("error\n");
    }
    return 0;
}
