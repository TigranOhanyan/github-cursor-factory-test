package reverse

import "testing"

func TestReverse(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{name: "empty", in: "", want: ""},
		{name: "ascii", in: "hello", want: "olleh"},
		{name: "unicode", in: "Hello, 世界", want: "界世 ,olleH"},
		{name: "accented", in: "café", want: "éfac"},
		{name: "emoji", in: "a😀b", want: "b😀a"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := Reverse(tt.in); got != tt.want {
				t.Errorf("Reverse(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}
