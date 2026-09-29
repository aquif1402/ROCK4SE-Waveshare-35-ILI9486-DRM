obj-m += drm_mipi_dbi.o
obj-m += ili9486.o

KDIR ?= /lib/modules/6.1.115-8-rk2501/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
