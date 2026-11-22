/* Mapa de memoria do bench.c no emulador: codigo em 0 (256 KB bastam) e RAM em 0x20000000, como no STM32F411. */
MEMORY { FLASH (rx): ORIGIN = 0x00000000, LENGTH = 256K  RAM (rwx): ORIGIN = 0x20000000, LENGTH = 128K }
SECTIONS { .text : { KEEP(*(.vetores)) *(.text*) *(.rodata*) } > FLASH
           .data : { _sdata = .; *(.data*) _edata = .; } > RAM AT > FLASH
           _sidata = LOADADDR(.data);
           .bss : { *(.bss*) *(COMMON) } > RAM }
