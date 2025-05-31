library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity Oscilloscope is
    Port (
        CLK : in  STD_LOGIC;
        CLK_ADC, CLK_DIV3 : out STD_LOGIC;
        ADin : in  STD_LOGIC_VECTOR (11 downto 0);
        SPI_MISO, test_output : out  STD_LOGIC;
        SPI_CS, OTR : in  STD_LOGIC;
        SPI_MOSI : in  STD_LOGIC;
        SPI_CLK : in  STD_LOGIC;
        ENC_A, ENC_B : in STD_LOGIC
    );
end Oscilloscope;

architecture Behavioral of Oscilloscope is

signal addr, addr2 : unsigned(15 downto 0) := (others => '0');
signal counter : integer range 0 to 49999999;
signal ADinreg : STD_LOGIC_VECTOR (11 downto 0);
signal CLK_DIV2, pCLK2 ,CLK_DIV4: STD_LOGIC := '0';

signal pSPI_CLK : STD_LOGIC;
signal shift_reg : STD_LOGIC_VECTOR(15 downto 0);
signal miso_reg : STD_LOGIC := '0';
signal bit_cnt : integer range 0 to 15;

signal sample_counter : integer range 0 to 1023 := 0;
signal sample_step : integer range 1 to 1024 := 1;
signal sample_clk : STD_LOGIC := '0';

-- Debounced rotary encoder signals
signal enc_a_sync, enc_b_sync : STD_LOGIC := '0';
signal enc_a_last, enc_b_last : STD_LOGIC := '0';
signal enc_state : STD_LOGIC_VECTOR(1 downto 0);
signal enc_last_state : STD_LOGIC_VECTOR(1 downto 0);

signal debounce_counter : integer range 0 to 50000 := 0;
signal debounce_ready : STD_LOGIC := '0';
signal adc_counter : integer range 0 to 3 :=0;

type MRAMT is array(0 to 8192) of STD_LOGIC_VECTOR(11 downto 0);
signal SRAM : MRAMT;

type state_type is (IDLE, WAIT_RISE, WRITE1, INCR_ADDR, DONE);
signal current_state, next_state : state_type := IDLE;
signal cmd_byte : STD_LOGIC_VECTOR(7 downto 0):= (others=>'0');

component CLK_GEN
port
 (-- Clock in ports
  CLK_IN1           : in     std_logic;
  -- Clock out ports
  CLK_OUT1          : out    std_logic;
  CLK_OUT2          : out    std_logic
 );
end component;


signal CLK_100Mhz,CLK_128Mhz : std_logic;

begin

   
    ADinreg <= ADin;
    CLK_DIV3 <= CLK_DIV4;
	 
	 
--	 process(CLK_128Mhz) is begin
--	 if(rising_edge(CLK_128Mhz)) then
--		if(adc_counter<2) then
--			adc_counter<=adc_counter+1;
--			else
--			CLK_DIV4<=not CLK_DIV4;
--			adc_counter<=0;
--			end if;
--	   end if;
--	end process;

	 process(CLK_128Mhz) is begin
	 if(rising_edge(CLK_128Mhz)) then
			CLK_DIV4<=not CLK_DIV4;
	   end if;
	end process;


	 
	 ADCClockComp : CLK_GEN
	port map
   (-- Clock in ports
    CLK_IN1 => CLK,
    -- Clock out ports
    CLK_OUT1 => CLK_100Mhz,
    CLK_OUT2 => CLK_128Mhz);
	 

    process(current_state, CLK_DIV2, pCLK2, addr) is
    begin
        next_state <= current_state;
        case current_state is
            when IDLE =>
                next_state <= WAIT_RISE;
            when WAIT_RISE =>
                if pCLK2 = '0' and CLK_DIV2 = '1' then
                    next_state <= WRITE1;
                end if;
            when WRITE1 =>
                next_state <= INCR_ADDR;
            when INCR_ADDR =>
                next_state <= IDLE;
            when DONE =>
                next_state <= IDLE;
        end case;
    end process;

    process(CLK_128Mhz) is
    begin
        if rising_edge(CLK_128Mhz) then
            current_state <= next_state;
            pCLK2 <= CLK_DIV2;

            case current_state is
                when WRITE1 =>
                    SRAM(to_integer(addr)) <= ADinreg;
                when INCR_ADDR =>
                    if(addr < 8192) then
                        addr <= addr + 1;
                    else
                        if(addr2 > 8189) then
                            addr <= (others => '0');
                        end if;
                    end if;
                when others => null;
            end case;
        end if;
    end process;

    -- Debouncer for rotary encoder
    process(CLK_128Mhz)
    begin
        if rising_edge(CLK_128Mhz) then
            if debounce_counter = 50000 then
                enc_a_sync <= ENC_A;
                enc_b_sync <= ENC_B;
                debounce_ready <= '1';
                debounce_counter <= 0;
            else
                debounce_counter <= debounce_counter + 1;
                debounce_ready <= '0';
            end if;
        end if;
    end process;

    process(CLK_128Mhz)
    begin
        if rising_edge(CLK_128Mhz) then
            if debounce_ready = '1' then
                enc_state <= enc_a_sync & enc_b_sync;
                if enc_state = "10" and enc_last_state = "00" then
                    if sample_step < 1000 then
                        sample_step <= sample_step + 10;
                    end if;
                elsif enc_state = "00" and enc_last_state = "10" then
                    if sample_step > 1 then
                        sample_step <= sample_step - 10;
                    end if;
                end if;
                enc_last_state <= enc_state;
            end if;
        end if;
    end process;

    -- Adjustable sampling clock
    process(CLK_128Mhz)
    begin
        if rising_edge(CLK_128Mhz) then
            if sample_counter = sample_step then
                sample_counter <= 0;
                sample_clk <= not sample_clk;
            else
                sample_counter <= sample_counter + 1;
            end if;
        end if;
    end process;

    CLK_DIV2 <= sample_clk;

    process(SPI_CS, SPI_CLK)
begin
    if (SPI_CS = '0') then
        if rising_edge(SPI_CLK) then

            -- Komut byte'ı oluştur (ilk 8 bitlik shift)
            if bit_cnt < 8 then
                cmd_byte(7 downto 1) <= cmd_byte(6 downto 0);
                cmd_byte(0) <= SPI_MOSI;
            end if;

            -- Sample_step gönderimi veya SRAM verisi
            if bit_cnt = 0 then
                if addr2 = 0 then
                    shift_reg(9 downto 0) <= std_logic_vector(to_unsigned(sample_step, 10));
                    shift_reg(15 downto 10) <= "000000";
                else
                    shift_reg(11 downto 0) <= SRAM(to_integer(addr2));
                    shift_reg(15 downto 12) <= "0000";
                end if;
            end if;

            miso_reg <= shift_reg(15 - bit_cnt);
            bit_cnt <= bit_cnt + 1;

            if bit_cnt = 15 then
                bit_cnt <= 0;

                -- SPI adres ilerlet
                if addr2 < 8192 then
                    addr2 <= addr2 + 1;
                else
                    addr2 <= (others => '0');
                end if;
            end if;

            -- Komut kontrolü: 0xAA geldiyse addr2'yi başa sar
            if cmd_byte = x"AA" then
                addr2 <= (others => '0');
            end if;

        end if;
    else
        bit_cnt <= 0;
    end if;
end process;


    SPI_MISO <= miso_reg;

end Behavioral;